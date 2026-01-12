import discord
from discord.ext import commands
from discord.ui import Button, View
from openai import AsyncOpenAI  # <--- 改用 AsyncOpenAI
import os
import json
import analysis 

# --- 讀取環境變數 ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- 初始化 Async OpenAI 客戶端 ---
if OPENAI_API_KEY:
    # 注意：這裡改用 AsyncOpenAI
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
else:
    print("⚠️ 警告: 未檢測到 OPENAI_API_KEY")
    openai_client = None

# --- 初始化 Discord Bot ---
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
        # 先 defer 回應，避免處理超時
        await interaction.response.defer()
        status_msg = await interaction.followup.send("🔍 正在調取市場數據並進行風險運算 (這可能需要 15-20 秒)...")
        
        # 移除按鈕
        self.stop()
        await interaction.message.edit(view=None)

        try:
            user_risk_pref = "未知"
            raw_text = self.user_input_raw
            if "保守" in raw_text or "低風險" in raw_text: user_risk_pref = "保守"
            elif "激進" in raw_text or "高風險" in raw_text: user_risk_pref = "激進"
            elif "穩健" in raw_text: user_risk_pref = "穩健"

            assets = self.asset_data['assets']
            
            # 1. 抓取數據 (這裡 analysis.py 還是同步的，但因為很快通常沒關係，若要極致優化也可改)
            metrics, total_score = analysis.fetch_market_data(assets)
            
            # 2. 畫圖
            chart_buffer = analysis.generate_charts(assets, total_score)
            chart_file = discord.File(chart_buffer, filename="analysis.png")
            
            # 3. AI 評論 (傳入 async client)
            # 注意：這裡我們呼叫 analysis 裡的函數，需確保 analysis 裡也有對應修改，
            # 但為了簡單起見，我們直接在 main.py 處理這段 AI 呼叫，避免改動 analysis.py 太大
            
            system_prompt = f"""
            你是一個專業的資產配置顧問。
            數據：風險分 {total_score:.1f}/100。
            用戶偏好：{user_risk_pref}。
            
            請給出兩段簡短評語：
            1. 風險等級與預期波動
            2. 優化建議
            """
            
            # 使用 await 非同步呼叫
            response = await openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(assets, ensure_ascii=False)}
                ],
                max_tokens=1000  # 限制長度，防止無限迴圈
            )
            critique = response.choices[0].message.content

            await status_msg.edit(content=critique, attachments=[chart_file])

        except Exception as e:
            await status_msg.edit(content=f"❌ 分析錯誤: {str(e)}")
            print(f"Stage 3 Error: {e}")

    @discord.ui.button(label="❌ 修改", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("已取消。", ephemeral=True)
        self.stop()
        await interaction.message.edit(view=None)

# --- Stage 1: 核心解析邏輯 ---
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
        # 使用 await 非同步呼叫 OpenAI
        response = await openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            response_format={"type": "json_object"}, 
            max_tokens=500, # 限制最大 Token 數，防止 27k 字的鬼打牆
            messages=[
                {
                    "role": "system", 
                    "content": """
                    你是一個資產配置「計算與標準化」引擎。
                    目標：輸出標準 JSON: {"assets": [{"name": "Ticker", "percentage": 30.5}], "total": 100}
                    
                    規則：
                    1. **單位統一**：將金額統一換算為 USD (假設 1 USD = 32 TWD) 計算權重。
                    2. **推算邏輯**：
                       - 若用戶混合金額與百分比，請嘗試推算總值。
                       - 範例: "A有$1000 (20%), B有..." -> 暗示總資產 $5000。
                    3. **模糊資產處理**：
                       - "AAA債卷ETF" -> name: "AGG" 或 "BND" (取代碼)
                       - "亂買的ETF" -> name: "Unknown ETF"
                       - "現金/Cash" -> name: "現金"
                    4. **錯誤處理**：
                       - 若數學邏輯不通或無法計算，回傳 {"status": "error", "message": "原因"}
                    """
                },
                {"role": "user", "content": user_input}
            ]
        )
        
        content = response.choices[0].message.content
        
        # 除錯：如果又發生錯誤，印出內容長度
        print(f"OpenAI Response Length: {len(content)}")
        if len(content) > 5000:
             await msg.edit(content="⚠️ AI 回傳內容過長，判定為運算錯誤，請簡化輸入。")
             return

        data = json.loads(content)
        
        if data.get("status") == "error":
            await msg.edit(content=f"⚠️ **無法解析**：{data.get('message')}")
            return

        view = ConfirmView(ctx.author, data, user_input)
        
        display_text = "### 📊 初步運算結果：\n"
        for a in data.get('assets', []):
            display_text += f"• **{a['name']}**: `{a['percentage']:.1f}%`\n"
            
        await msg.edit(content=display_text, view=view)

    except json.JSONDecodeError:
        # 捕捉 JSON 解析失敗 (通常是因為 AI 講廢話講太多導致被切斷)
        await msg.edit(content="❌ AI 運算發生格式錯誤，請再試一次。")
        print(f"JSON Error Content: {content[:200]}...") # 印出前200字除錯
    except Exception as e:
        await msg.edit(content=f"❌ 系統錯誤: {str(e)}")
        print(f"Error: {e}")

@bot.event
async def on_ready():
    print(f"Bot is ready: {bot.user}")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
