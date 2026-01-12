import discord
from discord.ext import commands
from discord.ui import Button, View
import openai
import os
import json
# 導入新寫的分析模組
import analysis 

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai_client = openai.Client(api_key=OPENAI_API_KEY)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

class ConfirmView(View):
    def __init__(self, original_author, asset_data, user_input_raw):
        super().__init__(timeout=180) # 延長 timeout 因為分析需要時間
        self.original_author = original_author
        self.asset_data = asset_data
        self.user_input_raw = user_input_raw # 保留原始輸入看有無提到風險偏好

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.original_author:
            await interaction.response.send_message("這不是你的資產配置喔！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ 確認正確", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        # 1. UI 回饋：讓用戶知道機器人正在工作
        await interaction.response.send_message("🔍 正在調取歷史數據、計算波動率並生成分析報告，請稍候約 10-15 秒...", ephemeral=False)
        self.stop() # 移除按鈕
        await interaction.message.edit(view=None)

        try:
            # 2. 提取風險偏好 (簡單關鍵字提取，或是可再串一次 AI)
            # 這裡簡單示範：如果用戶輸入包含 "保守", "激進" 等詞
            user_risk_pref = "未知"
            raw_text = self.user_input_raw
            if "保守" in raw_text or "低風險" in raw_text: user_risk_pref = "保守 (Conservative)"
            elif "激進" in raw_text or "高風險" in raw_text: user_risk_pref = "激進 (Aggressive)"
            elif "穩健" in raw_text: user_risk_pref = "穩健 (Moderate)"

            assets = self.asset_data['assets']

            # 3. 執行 Python 分析 (計算 Risk Score)
            # 這一步會去抓 yfinance 數據，可能需要幾秒
            metrics, total_score = analysis.fetch_market_data(assets)

            # 4. 生成圖表 (Matplotlib)
            chart_buffer = analysis.generate_charts(assets, total_score)
            chart_file = discord.File(chart_buffer, filename="analysis.png")

            # 5. 執行 AI 評價 (生成雙重評語)
            critique = await analysis.get_ai_critique(
                openai_client, 
                assets, 
                metrics, 
                total_score, 
                user_risk_pref
            )

            # 6. 發送最終報告
            final_embed = discord.Embed(
                title="📈 資產配置健檢報告",
                description=f"**風險評分**: `{total_score:.1f}/100`\n**用戶偏好**: `{user_risk_pref}`",
                color=0x00ff00 if total_score < 50 else 0xff0000
            )
            final_embed.set_image(url="attachment://analysis.png") # 引用附件圖片
            
            # 將 AI 的兩段評語分開放入 Embed Fields (更美觀)
            # 這裡假設 AI 輸出的格式有 ### 分隔，我們簡單處理直接顯示文字
            # 若要更精緻，可以用 split 切割 critique 字串
            
            await interaction.followup.send(content=critique, file=chart_file)

        except Exception as e:
            await interaction.followup.send(f"❌ 分析過程中發生錯誤: {str(e)}")
            print(e)

    @discord.ui.button(label="❌ 修改", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("已取消。", ephemeral=True)
        self.stop()
        await interaction.message.edit(view=None)

@bot.command(name="health")
async def health_check(ctx, *, user_input: str = None):
    if not user_input:
        await ctx.send("請輸入配置，例如：`!health 我很保守，持有 50% VOO, 50% 現金`")
        return

    msg = await ctx.send("🤖 正在解析配置...")

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            response_format={"type": "json_object"}, 
            messages=[
                {
                    "role": "system", 
                    "content": """
                    將用戶輸入轉為 JSON。
                    格式: {"assets": [{"name": "Ticker", "percentage": 30}, ...], "total": 100}
                    重要：請盡量將名稱轉為 Yahoo Finance 代碼 (如 台積電 -> 2330.TW, Apple -> AAPL)。
                    如果無法確定，保留原名。
                    """
                },
                {"role": "user", "content": user_input}
            ]
        )
        
        data = json.loads(response.choices[0].message.content)
        
        # 顯示確認介面
        # 注意：我們把原始輸入 user_input 傳進去，以便 Stage 3 提取風險偏好
        view = ConfirmView(ctx.author, data, user_input)
        
        display_text = "### 📋 確認您的配置：\n"
        for a in data['assets']:
            display_text += f"• {a['name']}: {a['percentage']}%\n"
            
        await msg.edit(content=display_text, view=view)

    except Exception as e:
        await msg.edit(content=f"Error: {e}")

@bot.event
async def on_ready():
    print(f"Bot is ready: {bot.user}")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
