import discord
from discord.ext import commands
from discord.ui import Button, View
import openai
import os
import json
import analysis  # 確保與 analysis.py 在同一目錄

# --- 讀取環境變數 ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 初始化 OpenAI 客戶端
if OPENAI_API_KEY:
    openai_client = openai.Client(api_key=OPENAI_API_KEY)
else:
    print("⚠️ 警告: 未檢測到 OPENAI_API_KEY")
    openai_client = None

# --- 初始化 Discord Bot (指令前綴改為 $) ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="$", intents=intents)

# --- 定義互動按鈕 (Stage 2) ---
class ConfirmView(View):
    def __init__(self, original_author, asset_data, user_input_raw):
        super().__init__(timeout=180) # 3分鐘超時
        self.original_author = original_author
        self.asset_data = asset_data
        self.user_input_raw = user_input_raw

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.original_author:
            await interaction.response.send_message("這不是你的資產配置喔！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ 確認正確，開始分析", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        # 1. 回應並鎖定按鈕
        await interaction.response.send_message("🔍 收到！正在調取市場數據、計算波動率並生成 AI 毒舌報告，請稍候約 15 秒...", ephemeral=False)
        self.stop()
        await interaction.message.edit(view=None)

        try:
            # 2. 提取風險偏好關鍵字
            user_risk_pref = "未知"
            raw_text = self.user_input_raw
            if "保守" in raw_text or "低風險" in raw_text: user_risk_pref = "保守 (Conservative)"
            elif "激進" in raw_text or "高風險" in raw_text: user_risk_pref = "激進 (Aggressive)"
            elif "穩健" in raw_text: user_risk_pref = "穩健 (Moderate)"

            assets = self.asset_data['assets']

            # 3. 執行 Python 分析 (Stage 3 - Risk Calculation)
            # 這一步會呼叫 analysis.py 去抓 Yahoo Finance
            metrics, total_score = analysis.fetch_market_data(assets)

            # 4. 生成圖表 (Matplotlib)
            chart_buffer = analysis.generate_charts(assets, total_score)
            chart_file = discord.File(chart_buffer, filename="analysis.png")

            # 5. 執行 AI 評價 (Stage 3 - AI Generation)
            critique = await analysis.get_ai_critique(
                openai_client, 
                assets, 
                metrics, 
                total_score, 
                user_risk_pref
            )

            # 6. 發送最終報告
            await interaction.followup.send(content=critique, file=chart_file)

        except Exception as e:
            await interaction.followup.send(f"❌ 分析過程中發生錯誤: {str(e)}")
            print(f"Analysis Error: {e}")

    @discord.ui.button(label="❌ 修改 / 取消", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("已取消。請重新整理您的敘述後，再次輸入 `$health`。", ephemeral=True)
        self.stop()
        await interaction.message.edit(view=None)

# --- 核心指令 $health (Stage 1) ---
@bot.command(name="health")
async def health_check(ctx, *, user_input: str = None):
    if not openai_client:
        await ctx.send("❌ 錯誤：Bot 尚未設定 OpenAI API Key。")
        return

    if not user_input:
        await ctx.send("請輸入您的配置，例如：`$health 我很保守，持有 50% VOO, 50% 現金`")
        return

    msg = await ctx.send("🤖 正在讀取您的配置並進行結構化處理...")

    try:
        # 呼叫 OpenAI 進行 Stage 1 解析
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            response_format={"type": "json_object"}, 
            messages=[
                {
                    "role": "system", 
                    "content": """
                    你是一個資產配置 JSON 解析器。
                    任務：將用戶輸入轉換為標準 JSON。
                    
                    規則：
                    1. 將所有資產轉為 List，格式：{"name": "Ticker", "percentage": 30}
                    2. **關鍵代碼轉換** (非常重要)：
                       - 如果用戶說「現金」、「台幣」、「美元」、「Cash」，name 請一律填 "現金" (這將觸發特殊的零波動率處理)。
                       - 嘗試將股票名稱轉為 Yahoo Finance 代碼：
                         * 台積電 -> "2330.TW"
                         * 鴻海 -> "2317.TW"
                         * 聯發科 -> "2454.TW"
                         * 輝達/Nvidia -> "NVDA"
                         * 蘋果 -> "AAPL"
                         * 特斯拉 -> "TSLA"
                         * 標普500/大盤 -> "VOO"
                         * 那斯達克/科技股 -> "QQQ"
                       - 若無法確定代碼，請保留原名。
                    3. 確保 "assets" 列表和 "total" (總百分比) 存在。
                    
                    範例：
                    Input: "一半台積電，一半放定存"
                    Output: {"assets": [{"name": "2330.TW", "percentage": 50}, {"name": "現金", "percentage": 50}], "total": 100}
                    """
                },
                {"role": "user", "content": user_input}
            ]
        )
        
        # 解析回傳結果
        data = json.loads(response.choices[0].message.content)
        
        # 顯示確認介面 (Stage 2)
        view = ConfirmView(ctx.author, data, user_input)
        
        display_text = "### 📋 請確認您的資產配置：\n"
        for a in data.get('assets', []):
            display_text += f"• **{a['name']}**: `{a['percentage']}%`\n"
        
        if data.get('total') != 100:
            display_text += f"\n⚠️ **注意**：目前加總為 `{data.get('total')}%` (非 100%)"
            
        await msg.edit(content=display_text, view=view)

    except Exception as e:
        await msg.edit(content=f"❌ 解析失敗: {str(e)}")
        print(f"Parsing Error: {e}")

# --- Bot 啟動事件 ---
@bot.event
async def on_ready():
    print(f"Bot is ready: {bot.user} (ID: {bot.user.id})")
    print("-------------------------------------------------")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ 請設定 DISCORD_TOKEN 環境變數")
