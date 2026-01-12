import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import io
import json
import os
import requests

# --- 1. 自動解決中文字型問題 ---
# 設定中文字型檔名
FONT_FILENAME = "NotoSansTC-Regular.ttf"
FONT_URL = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf"

def get_chinese_font():
    """檢查是否有中文字型，沒有就下載，並回傳 FontProperties"""
    if not os.path.exists(FONT_FILENAME):
        print("📥 正在下載中文字型 (第一次運行會比較久)...")
        try:
            r = requests.get(FONT_URL)
            with open(FONT_FILENAME, 'wb') as f:
                f.write(r.content)
            print("✅ 字型下載完成")
        except Exception as e:
            print(f"⚠️ 字型下載失敗: {e}")
            return None # 回傳 None 讓它用預設字型
    return fm.FontProperties(fname=FONT_FILENAME)

# 取得字型物件 (全域變數)
zh_font = get_chinese_font()

# 設定圖表風格
plt.style.use('dark_background')

def fetch_market_data(assets):
    """
    抓取數據並計算波動率
    """
    metrics = {}
    valid_tickers = []
    
    # 1. 先過濾掉現金，不要去查 Yahoo
    for asset in assets:
        name = asset['name'].strip()
        # 判斷是否為現金 (中英文皆可)
        if name.upper() in ['CASH', 'USD', 'TWD', 'USDT', '現金', '美元', '台幣']:
            metrics[name] = 0.0 # 現金波動率為 0
        else:
            valid_tickers.append(name)

    # 2. 批量抓取剩餘股票數據
    if valid_tickers:
        print(f"🔍 正在查詢 Tickers: {valid_tickers}")
        try:
            # 這裡把 auto_adjust=True 加入，避免除權息導致的假缺口
            data = yf.download(valid_tickers, period="1y", progress=False, auto_adjust=True)['Close']
            
            # 如果只有一檔股票，Series 轉 DataFrame
            if isinstance(data, pd.Series):
                data = data.to_frame(name=valid_tickers[0])
            
            # 計算波動率
            for ticker in valid_tickers:
                if ticker in data.columns:
                    # 處理數據：移除空值 -> 算漲跌幅 -> 移除空值
                    clean_series = data[ticker].dropna()
                    if len(clean_series) > 10: # 確保數據足夠
                        returns = clean_series.pct_change().dropna()
                        vol = returns.std() * np.sqrt(252) * 100
                        
                        # 補救措施：如果算出來是 NaN (例如數據全一樣)，設為 0
                        if np.isnan(vol): vol = 0.0
                        
                        metrics[ticker] = vol
                    else:
                        metrics[ticker] = 20.0 # 數據不足的預設值
                else:
                    # 抓不到數據的 (可能下市或打錯字)
                    metrics[ticker] = 20.0 
                    print(f"⚠️ 無法取得數據: {ticker}，使用預設波動率")

        except Exception as e:
            print(f"❌ Yahoo Finance 下載錯誤: {e}")
            # 發生大錯誤時，全部給預設值，避免程式崩潰
            for t in valid_tickers: metrics[t] = 20.0

    # 3. 計算總分
    total_score = 0
    total_weight = 0
    
    for asset in assets:
        name = asset['name']
        pct = asset['percentage']
        vol = metrics.get(name, 20.0) # 取不到就給 20
        
        # 再次確保不是 NaN
        if np.isnan(vol): vol = 20.0
            
        risk_score = min(vol * 2.5, 100)
        total_score += risk_score * (pct / 100)
        total_weight += pct

    return metrics, total_score

def generate_charts(assets, total_score):
    """
    生成圓餅圖
    """
    labels = [a['name'] for a in assets]
    sizes = [a['percentage'] for a in assets]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6)) # 加大一點
    
    # 1. 圓餅圖
    colors = plt.cm.Set3(np.linspace(0, 1, len(assets)))
    wedges, texts, autotexts = ax1.pie(sizes, labels=labels, autopct='%1.1f%%', 
                                       startangle=90, colors=colors)
    
    ax1.set_title("資產配置 (Portfolio)", fontproperties=zh_font, color='white', fontsize=16)
    
    # 修正字型
    if zh_font:
        for text in texts: text.set_fontproperties(zh_font)
        for text in autotexts: text.set_fontproperties(zh_font)
        
    for text in texts + autotexts:
        text.set_color('white')

    # 2. 風險條
    # 避免 NaN 導致報錯
    if np.isnan(total_score): total_score = 0
    
    risk_color = 'green' if total_score < 40 else 'orange' if total_score < 70 else 'red'
    ax2.barh(['Risk Score'], [total_score], color=risk_color, height=0.3)
    ax2.set_xlim(0, 100)
    
    # 主標題
    ax2.set_title(f"風險評分: {total_score:.1f}/100", fontproperties=zh_font, color=risk_color, fontsize=18, fontweight='bold')
    
    # 刻度標籤
    ax2.text(10, 0, "保守 (Conservative)", fontproperties=zh_font, color='white', ha='center', va='bottom', fontsize=10)
    ax2.text(50, 0, "穩健 (Moderate)", fontproperties=zh_font, color='white', ha='center', va='bottom', fontsize=10)
    ax2.text(90, 0, "激進 (Aggressive)", fontproperties=zh_font, color='white', ha='center', va='bottom', fontsize=10)
    ax2.axis('off')

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', transparent=True)
    buf.seek(0)
    plt.close()
    
    return buf

async def get_ai_critique(client, assets, metrics, total_score, user_risk_pref=None):
    portfolio_summary = json.dumps(assets, ensure_ascii=False)
    metrics_summary = json.dumps(metrics, ensure_ascii=False) # 轉成字串避免 NaN 錯誤

    system_prompt = f"""
    你是一個華爾街等級的毒舌資產配置顧問。
    數據：
    - 投資組合風險分：{total_score:.1f} (0=定存, 100=加密貨幣全倉)。
    - 個別資產年化波動率：{metrics_summary} (現金通常為0，大盤約15-20，個股30+)。
    - 用戶自述偏好：{user_risk_pref if user_risk_pref else "未說明"}。

    請根據「真實數據」給出兩段回覆（不要客套，直接切入重點）：

    ### 1. 風險等級與預期波動 📉
    告訴用戶這個分數代表什麼。如果他的配置裡有高波動個股（如 TSMC, NVDA）但現金很少，請警告他崩盤時會很痛。如果全是現金，請嘲笑他被通膨吃掉購買力。
    **必須引用上面的數據**（例如：「你的台積電波動高達 32%，是市場的兩倍...」）。

    ### 2. 優化建議與執行策略 🚀
    給出 2-3 個具體操作建議。
    - 如果太集中：建議補債券 (TLT, BND) 或 全球市場 (VT)。
    - 如果太保守：建議定期定額 VOO。
    - 確保建議可行。
    """

    response = client.chat.completions.create(
        model="gpt-4-turbo-preview",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"資產列表: {portfolio_summary}"}
        ]
    )
    return response.choices[0].message.content
