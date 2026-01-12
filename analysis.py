# analysis.py
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import json

# 設定圖表風格為暗色，適配 Discord
plt.style.use('dark_background')

def fetch_market_data(assets):
    """
    使用 yfinance 抓取歷史數據並計算波動率
    assets: list of dict [{'name': 'VOO', 'percentage': 30}, ...]
    """
    tickers = [a['name'] for a in assets if a['name'].upper() != 'CASH']
    if not tickers:
        return {}, 0.0

    # 抓取過去 1 年數據
    try:
        data = yf.download(tickers, period="1y", progress=False)['Close']
    except Exception as e:
        print(f"Data fetch error: {e}")
        return {}, 0.0

    # 處理單一股票與多股票的格式差異
    if isinstance(data, pd.Series):
        data = data.to_frame(name=tickers[0])

    asset_metrics = {}
    portfolio_volatility = 0.0
    
    # 計算個別資產波動率 (年化)
    for ticker in tickers:
        if ticker in data.columns:
            returns = data[ticker].pct_change().dropna()
            vol = returns.std() * np.sqrt(252) * 100 # 轉為百分比
            asset_metrics[ticker] = vol
        else:
            asset_metrics[ticker] = 20.0 # 抓不到數據時的預設值 (市場平均)

    # 計算加權風險分數 (簡化版邏輯)
    total_score = 0
    total_weight = 0
    
    for asset in assets:
        name = asset['name']
        pct = asset['percentage']
        
        if name.upper() == 'CASH':
            vol = 0
        else:
            # 如果 yfinance 抓不到，給一個預設波動率
            vol = asset_metrics.get(name, 20.0) 
            
        # 風險分數公式：波動率 * 2.5 (原本代碼的邏輯) 限制在 100
        risk_score = min(vol * 2.5, 100)
        
        total_score += risk_score * (pct / 100)
        total_weight += pct

    return asset_metrics, total_score

def generate_charts(assets, total_score):
    """
    生成圓餅圖與風險儀表板，回傳 BytesIO 物件
    """
    labels = [a['name'] for a in assets]
    sizes = [a['percentage'] for a in assets]
    
    # 建立畫布：左邊圓餅，右邊風險條
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))
    
    # 1. 圓餅圖
    colors = plt.cm.Set3(np.linspace(0, 1, len(assets)))
    wedges, texts, autotexts = ax1.pie(sizes, labels=labels, autopct='%1.1f%%', 
                                       startangle=90, colors=colors)
    ax1.axis('equal')
    ax1.set_title("Portfolio Allocation", color='white', fontsize=14)
    
    # 調整文字顏色
    for text in texts + autotexts:
        text.set_color('white')

    # 2. 風險分數條 (簡單模擬儀表板)
    risk_color = 'green' if total_score < 40 else 'orange' if total_score < 70 else 'red'
    ax2.barh(['Risk Score'], [total_score], color=risk_color, height=0.3)
    ax2.set_xlim(0, 100)
    ax2.set_title(f"Risk Level: {total_score:.1f}/100", color=risk_color, fontsize=16, fontweight='bold')
    
    # 加一些標註
    ax2.text(10, 0, "Conservative", color='white', ha='center', va='bottom', fontsize=8)
    ax2.text(50, 0, "Moderate", color='white', ha='center', va='bottom', fontsize=8)
    ax2.text(90, 0, "Aggressive", color='white', ha='center', va='bottom', fontsize=8)
    ax2.axis('off') # 隱藏座標軸

    # 存到記憶體
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', transparent=True)
    buf.seek(0)
    plt.close()
    
    return buf

async def get_ai_critique(client, assets, metrics, total_score, user_risk_pref=None):
    """
    呼叫 OpenAI 生成雙重評語
    """
    
    # 準備給 AI 的數據
    portfolio_summary = json.dumps(assets, ensure_ascii=False)
    risk_gap_context = ""
    
    if user_risk_pref:
        risk_gap_context = f"用戶自述風險偏好為：'{user_risk_pref}'。請比對計算出的風險分數 ({total_score:.1f}/100) 與用戶偏好是否一致。"
    else:
        risk_gap_context = "用戶未提供具體風險偏好，請以一般大眾標準評估。"

    system_prompt = f"""
    你是一個專業、犀利且注重實戰的資產配置顧問。
    目前計算出的投資組合風險分數為：{total_score:.1f} (0=現金, 100=極高波動)。
    個別資產波動率數據：{metrics}
    
    {risk_gap_context}

    請輸出兩段內容，不需要開場白，直接輸出：

    ### 1. 風險等級與預期波動
    (請解釋這個分數代表什麼。例如：這樣的配置在金融海嘯時可能會跌多少？每年的預期波動大概是幾趴？如果分數很高但用戶偏好低風險，請這裡直接點出「你的配置與你的心臟強度不符」。)

    ### 2. 優化建議與執行策略
    (針對目前的缺點給出具體建議。例如：現金太多導致拖累績效、科技股太集中需要分散。如果用戶偏好低風險但配置高風險，請給出「降轉建議」；反之則給出「增強收益建議」。)
    """

    response = client.chat.completions.create(
        model="gpt-4-turbo-preview",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"資產列表: {portfolio_summary}"}
        ]
    )
    
    return response.choices[0].message.content
