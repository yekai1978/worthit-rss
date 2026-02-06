import streamlit as st
import feedparser
import google.generativeai as genai
from openai import OpenAI
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import json_repair
import time
import os
import requests
import re
import base64
from gtts import gTTS
import concurrent.futures

# ================= 1. 工程配置 =================

st.set_page_config(page_title="WorthIt V3.0 完美收官", page_icon="🦁", layout="wide")

# 端口配置
PROXY_PORT = "3067"
os.environ["http_proxy"] = f"http://127.0.0.1:{PROXY_PORT}"
os.environ["https_proxy"] = f"http://127.0.0.1:{PROXY_PORT}"

# 读取密钥
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
DEEPSEEK_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")

# 状态检查
has_gemini = len(GEMINI_KEY) > 10
has_deepseek = len(DEEPSEEK_KEY) > 10

# ================= 2. 强力抓取器 (解决 0 结果问题) =================

def fetch_feed_safe(url):
    """
    🥷 伪装成浏览器去抓取 RSS，防止被拦截
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        # 先用 requests 伪装下载
        resp = requests.get(url, headers=headers, timeout=10)
        # 再把内容给 feedparser 解析
        return feedparser.parse(resp.content)
    except:
        return None

# ================= 3. AI 引擎 (排版优化版) =================

class AI_Engine:
    def _call_deepseek_raw(self, prompt):
        if not has_deepseek: return "DeepSeek 未配置"
        try:
            client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=1.3 # 稍微高一点，让行文更自然
            )
            return response.choices[0].message.content
        except Exception as e: return f"DeepSeek Error: {e}"

    def _call_gemini_raw(self, prompt):
        if not has_gemini: return "Gemini 未配置"
        try:
            genai.configure(api_key=GEMINI_KEY)
            # 尝试最基础的模型，防 404
            model = genai.GenerativeModel('gemini-pro') 
            response = model.generate_content(prompt)
            return response.text
        except Exception as e: return f"Gemini Error: {e}"

    def generate_single(self, prompt, engine_name):
        if engine_name == "DeepSeek": return self._call_deepseek_raw(prompt)
        else: return self._call_gemini_raw(prompt)

    def generate_fusion(self, prompt, context_data):
        # 双核任务
        task_prompt = f"""
        阅读资料：
        {context_data[:5000]}
        
        用户问题：{prompt}
        要求：深度分析，逻辑清晰。
        """
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_ds = executor.submit(self._call_deepseek_raw, task_prompt)
            if has_gemini:
                future_ge = executor.submit(self._call_gemini_raw, task_prompt)
                res_ge = future_ge.result()
            else:
                res_ge = "Gemini Skipped"
            res_ds = future_ds.result()

        # 融合 Prompt (强调排版)
        fusion_prompt = f"""
        Role: Senior Editor.
        Task: Merge two reports into one PERFECTLY FORMATTED report.
        
        Report A (DeepSeek): {res_ds[:4000]}
        Report B (Gemini): {res_ge[:4000]}
        
        FORMATTING RULES (STRICT):
        1. Use `##` for main sections.
        2. Use `###` for subsections.
        3. Use `- ` (bullet points) for lists.
        4. Use `**Bold**` for key terms.
        5. Insert blank lines between paragraphs.
        
        Output: Chinese Markdown.
        """
        return self._call_deepseek_raw(fusion_prompt), res_ds, res_ge

# ================= 4. 业务逻辑 (核心 Prompt 修改) =================

class Sanitizer:
    @staticmethod
    def clean(text):
        if not text: return ""
        text = str(text)
        try:
            soup = BeautifulSoup(text, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
        except: text = re.sub(r'<[^>]+>', '', text)
        return re.sub(r'\s+', ' ', text).strip()

def safe_extract_image(entry):
    try:
        if 'media_content' in entry and entry.media_content: return entry.media_content[0]['url']
        if 'media_thumbnail' in entry and entry.media_thumbnail: return entry.media_thumbnail[0]['url']
        soup = BeautifulSoup(entry.get('summary', ''), 'html.parser')
        img = soup.find('img')
        if img: return img.get('src')
    except: pass
    return None

def analyze_item(item, mode, engine_name):
    engine = AI_Engine()
    raw_summary = Sanitizer.clean(item.get('summary', ''))
    title = item['title']
    
    # 提示词工程：强制排版
    role = "Senior Tech Editor"
    if mode == "movie": role = "Film Critic"
    
    prompt = f"""
    Role: {role}
    Task: Translate & Summarize into Simplified Chinese.
    
    Source Title: {title}
    Source Content: {raw_summary[:3000]}
    
    OUTPUT FORMAT REQUIREMENTS (CRITICAL):
    1. **Title**: Catchy Chinese Title.
    2. **Summary**:
       - MUST be structured with clear paragraphs.
       - Use `**` to bold key entities (People, Companies, Products).
       - If there are multiple points, use a list format:
         * Point 1
         * Point 2
    3. **Tags**: 3-5 keywords.
    
    Output JSON ONLY: {{ "score": 85, "title_cn": "...", "summary": "Markdown content...", "tags": ["..."] }}
    """

    retries = 2
    for i in range(retries):
        try:
            res_text = engine.generate_single(prompt, engine_name)
            res = json_repair.repair_json(res_text, return_objects=True)
            if not res.get('summary'): raise ValueError("Empty")
            return res
        except:
            if engine_name == "Gemini": time.sleep(2)
            else: time.sleep(1)
            continue
            
    return {"score": 0, "title_cn": title, "summary": raw_summary, "tags": ["Fail"], "status": "fallback"}

# ================= 5. UI 主界面 =================

st.title("🦁 WorthIt V3.0 完美收官版")

with st.sidebar:
    st.header("🎛️ 引擎选择")
    # 默认选 DeepSeek，因为 Gemini 经常报错
    engine_choice = st.radio("主引擎:", ["DeepSeek", "Gemini"], index=0 if has_deepseek else 1)
    
    st.divider()
    if has_deepseek: st.success("✅ DeepSeek 就绪")
    if has_gemini: st.info("ℹ️ Gemini 就绪 (注意配额)")

t1, t2, t3, t4 = st.tabs(["🌍 全球新闻", "🎬 影视前线", "🎸 酷玩硬件", "🧠 双核特工"])

# 增加了国内更容易访问的源，解决“0结果”
SOURCES = {
    "news": {
        "Techmeme": "https://www.techmeme.com/feed.xml",
        "Nature": "https://www.nature.com/nature.rss"
    },
    "movie": {
        "Variety": "https://variety.com/v/film/feed/", 
        "HollywoodReporter": "https://www.hollywoodreporter.com/c/movies/movie-news/feed/"
    },
    "gear": {
        "Engadget": "https://www.engadget.com/rss.xml", # 强力抓取
        "TheVerge": "https://www.theverge.com/rss/circuit-breaker/index.xml" 
    }
}

def render_feed(src_dict, mode):
    items = []
    seen = set()
    status = st.empty()
    status.info(f"📡 {engine_choice} 正在强力抓取中 (已启用反爬虫伪装)...")
    
    for s, u in src_dict.items():
        # 使用强力抓取器
        f = fetch_feed_safe(u)
        if f:
            for e in f.entries[:3]:
                if e.link not in seen:
                    items.append({'title': e.title, 'link': e.link, 'summary': e.summary if 'summary' in e else '', 'image': safe_extract_image(e), 'source': s})
                    seen.add(e.link)
        
    processed = []
    bar = st.progress(0)
    
    for i, item in enumerate(items):
        bar.progress((i)/len(items))
        if engine_choice == "Gemini": time.sleep(4) # 避开 429
        
        res = analyze_item(item, mode, engine_choice)
        item.update(res)
        processed.append(item)
        
    status.empty()
    bar.empty()
    processed.sort(key=lambda x: int(x.get('score', 0)), reverse=True)
    
    for item in processed:
        score = int(item.get('score', 0))
        color = "#ff4b4b" if score >= 80 else "#ffa421"
        with st.container(border=True):
            has_img = item.get('image') and mode in ['movie', 'gear']
            c1, c2 = st.columns([3, 1]) if has_img else st.columns([1, 0.01])
            with c1:
                st.markdown(f"### {item['title_cn']}")
                st.caption(f"Source: {item['source']} | Tags: {item.get('tags')}")
                
                # 渲染优化：确保 Markdown 生效
                st.markdown(item['summary'])
                
                with st.expander("🔗 原文与工具"):
                     st.markdown(f"[阅读原文]({item['link']})")
            if has_img:
                with c2:
                    st.image(item['image'], use_container_width=True)
                    st.markdown(f"<h1 style='color:{color};text-align:center'>{score}</h1>", unsafe_allow_html=True)

with t1:
    if st.button("🚀 扫描新闻"): render_feed(SOURCES['news'], "news")
with t2:
    if st.button("🎥 扫描影视"): render_feed(SOURCES['movie'], "movie")
with t3:
    if st.button("🎸 扫描硬件"): render_feed(SOURCES['gear'], "gear")

with t4:
    st.markdown("### 🕵️ 双核情报局 (排版增强版)")
    q = st.text_input("请输入指令")
    if st.button("🔍 启动"):
        engine = AI_Engine()
        with st.spinner("双核引擎正在全速运转..."):
            # 简化逻辑：特工模式直接用 search (需自行添加 NetworkOps 类或保留旧代码，此处简化展示)
            # 为保证代码完整性，这里复用之前的 search 逻辑
            from duckduckgo_search import DDGS
            ctx = ""
            try:
                with DDGS() as ddgs:
                    for r in list(ddgs.text(q, max_results=5)): ctx += r['body']
            except: ctx = "Internal Knowledge"
            
            final, _, _ = engine.generate_fusion(q, ctx)
            st.markdown(final)