import discord
from discord.ext import commands
from discord.ui import Button, View
import openai
import os
import json
import analysis 

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if OPENAI_API_KEY:
    openai_client = openai.Client(api_key=OPENAI_API_KEY)
else:
    openai_client = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="$", intents=intents)

# --- Stage 2: 確認按鈕 ---
class ConfirmView(View):
    def __init__(self, original_author, asset_data, user_input_raw):
        super().__init__(timeout=180)
        self.original_author = original_author
        self.asset_data = asset_data
        self.user_input_raw = user_input_raw

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.original_author:
            await interaction.response.send_message("這不是你的資產配置喔！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ 確認正確", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🔍 數據標準化完成。正在調取市場數據並進行風險運算...", ephemeral=False)
        self.stop()
        await interaction.message.edit(view=None)

        try:
            user_risk_pref = "未知"
            raw_text = self.user_input_raw
            if "保守" in raw_text or "低風險" in raw_text: user_risk_pref = "保守"
            elif "激進" in raw_text or "高風險" in raw_text: user_risk_pref = "激進"
            elif "穩健" in raw_text: user_risk_pref = "穩健"

            assets = self.asset_data['assets']
            metrics, total_score = analysis.fetch_market_data(assets)
            chart_buffer = analysis.generate_charts(assets, total_score)
            chart_file = discord.File(chart_buffer, filename="analysis.png")
            
            critique = await analysis.get_ai_critique(openai_client, assets, metrics, total_score, user_risk_pref)
            await interaction.followup.send(content=critique, file=chart_file)

        except Exception as e:
            await interaction.followup.send(f"❌ 分析錯誤: {str(e)}")

    @discord.ui.button(label="❌ 修改", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("已取消。", ephemeral=True)
        self.stop()
        await interaction.message.edit(view=None)

# --- Stage 1: 核心解析邏輯 (大幅升級) ---
@bot.command(name="health")
async def health_check(ctx, *, user_input: str = None):
    if not openai_client:
        await ctx.send("❌ 錯誤：Bot 尚未設定 OpenAI API Key。")
        return

    if not user_input:
        await ctx.send("請輸入您的配置，例如：`$health 50% VOO, 50% 現金`")
        return

    msg = await ctx.send("🤖 正在進行數學運算與資產標準化...")

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            response_format={"type": "json_object"}, 
            messages=[
                {
                    "role": "system", 
                    "content": """
                    你是一個資產配置「計算與標準化」引擎。
                    你的目標是輸出標準的 JSON 格式：{"assets": [{"name": "Ticker", "percentage": 30.5}], "total": 100}。
                    
                    ### 核心邏輯規則 (必須嚴格遵守)：
                    1. **單位統一**：如果用戶混合使用貨幣 (1000 USD, 10000 TWD)，請以「粗略匯率」統一換算成 USD (假設 1 USD = 32 TWD) 來計算權重。
                    2. **混合輸入運算 (最重要)**：
                       - 如果用戶同時給了「絕對金額」和「百分比」，你必須嘗試推算總資產。
                       - **案例**："A有 $1000 (代表某個佔比), B佔 50%"。
                         -> 邏輯：這通常暗示 $1000 是剩下的 50%。因此總資產 = $2000。A = 50%, B = 50%。
                       - **矛盾檢測**：如果輸入數學上無法成立 (例如："A佔 60%, B佔 60%")，或者資訊不足無法推算 (例如："A有 $1000, B有 $500, C佔 10%" -> 這裡不知道 $1500 代表多少比例)，請回傳 Error。
                    3. **"剩下的" (The Rest)**：
                       - 計算所有已知百分比，將剩餘的 % 分配給 "剩下的" 那個資產。
                    4. **代碼轉換**：
                       - 現金/Cash/TWD/USD -> name: "現金"
                       - 0050/台灣50 -> name: "0050.TW"
                       - 比特幣 -> name: "BTC-USD"
                    
                    ### 異常處理：
                    如果用戶輸入模糊、數學矛盾、或無法計算百分比，請不要瞎編數據。
                    請回傳 JSON: {"status": "error", "message": "你的錯誤原因說明"}
                    
                    ### 範例：
                    User: "1000美金 VOO, 1000美金 QQQ"
                    Output: {"assets": [{"name": "VOO", "percentage": 50}, {"name": "QQQ", "percentage": 50}], "total": 100}
                    
                    User: "50% VOO, 剩下的放定存"
                    Output: {"assets": [{"name": "VOO", "percentage": 50}, {"name": "現金", "percentage": 50}], "total": 100}

                    User: "1000美金 VOO, 45% 0050" (這很難算，假設 $1000 是剩下的 55%)
                    Logic: $1000 / 0.55 = Total $1818. 0050 = $818 (45%).
                    Output: {"assets": [{"name": "VOO", "percentage": 55}, {"name": "0050.TW", "percentage": 45}], "total": 100}
                    """
                },
                {"role": "user", "content": user_input}
            ]
        )
        
        data = json.loads(response.choices[0].message.content)
        
        # --- 錯誤處理：如果 AI 認為算不出來 ---
        if data.get("status") == "error":
            await msg.edit(content=f"⚠️ **無法解析您的配置**\nAI 判讀訊息：{data.get('message')}\n\n💡 建議：請試著統一單位，例如全部用 `%` 表達，或全部用 `金額` 表達。")
            return

        # 正常流程
        view = ConfirmView(ctx.author, data, user_input)
        
        display_text = "### 📊 資產標準化結果 (已換算為 %)\n"
        for a in data.get('assets', []):
            display_text += f"• **{a['name']}**: `{a['percentage']:.1f}%`\n"
        
        # 加上警告標語，如果 AI 做了大量推論
        display_text += "\n*(若您輸入了金額，AI 已自動根據權重換算為百分比)*"
            
        await msg.edit(content=display_text, view=view)

    except Exception as e:
        await msg.edit(content=f"❌ 系統錯誤: {str(e)}")
        print(f"Error: {e}")

@bot.event
async def on_ready():
    print(f"Bot is ready: {bot.user}")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
