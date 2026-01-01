import streamlit as st
import re
import sys
import asyncio
import warnings
from playwright.sync_api import sync_playwright

# ✅ Playwright subprocess fix for Windows + Python 3.14
# ✅ Hide deprecation warning safely
if sys.platform.startswith("win"):
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# -----------------------------
# Page Setup + Hide Sidebar
# -----------------------------
st.set_page_config(page_title="GIPHY Tag Extractor Tool", page_icon="✨", layout="wide")

hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
section[data-testid="stSidebar"] {display: none;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# -----------------------------
# CSS Styling (Premium UI)
# -----------------------------
st.markdown("""
<style>
.main-title {
    font-size: 38px;
    font-weight: 900;
    color:#111827;
    margin-bottom: 6px;
}
.sub-title {
    font-size: 15px;
    color:#6b7280;
    font-weight: 500;
    margin-bottom: 25px;
}
.panel {
    background: #ede4e3;
    padding: 2px;
    border-radius: 2px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 8px 22px rgba(0,0,0,0.06);
    margin-bottom: 18px;
}
.section-title {
    font-size: 22px;
    font-weight: 900;
    margin-bottom: 10px;
    margin-top: 6px;
}
.section-title2 {
    font-size: 15px;
    font-weight: 700;
    margin-bottom: 3px;
    margin-top: 6px;
}
.badge {
    display:inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    margin-right: 8px;
    color: white;
}
.badge-blue { background:#2563eb; }
.badge-green { background:#16a34a; }
.badge-purple { background:#7c3aed; }

.tag-chip {
    display:inline-block;
    padding:7px 12px;
    border-radius:18px;
    border:2px solid #fbbf24;
    background:#fff7ed;
    color:#111827;
    margin:5px 6px 0 0;
    font-size:14px;
    font-weight:800;
}
.common-chip {
    display:inline-block;
    padding:7px 12px;
    border-radius:18px;
    border:2px solid #22c55e;
    background:#ecfdf5;
    color:#065f46;
    margin:5px 6px 0 0;
    font-size:14px;
    font-weight:900;
}
.flex-wrap {
    display:flex;
    flex-wrap:wrap;
    gap:6px;
    margin-top:10px;
}
.copy-box {
    background:#f9fafb;
    border:1px solid #e5e7eb;
    padding:12px;
    border-radius:12px;
    font-family: monospace;
    font-size: 14px;
    color:#111827;
    margin-top:10px;
    word-wrap: break-word;
}
.title-link {
    font-size: 21px;
    font-weight: 900;
    color: #111827;
    text-decoration:none;
}
.title-link:hover {
    text-decoration:underline;
}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# Session State Setup
# -----------------------------
if "gif_links" not in st.session_state:
    st.session_state.gif_links = ""

if "keyword" not in st.session_state:
    st.session_state.keyword = ""

if "results" not in st.session_state:
    st.session_state.results = []

if "common_tags" not in st.session_state:
    st.session_state.common_tags = []

if "suggested_tags" not in st.session_state:
    st.session_state.suggested_tags = []

# ✅ NEW: comparison selections
if "compare_selected" not in st.session_state:
    st.session_state.compare_selected = []

if "compare_select_all" not in st.session_state:
    st.session_state.compare_select_all = False

# ✅ NEW: recommended tags
if "recommended_tags" not in st.session_state:
    st.session_state.recommended_tags = []

# -----------------------------
# Helpers
# -----------------------------
def normalize_tag(t: str) -> str:
    t = str(t).strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    t = t.strip()
    if not t:
        return ""
    return "#" + t

def strip_hash(tag: str) -> str:
    return tag[1:] if tag.startswith("#") else tag

def unique_order(items):
    seen = set()
    out = []
    for x in items:
        k = x.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out

def clean_title(title: str) -> str:
    if not title:
        return "(no title)"
    title = re.sub(r"\s*-\s*Find\s*&\s*Share\s*on\s*GIPHY\s*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*-\s*GIPHY\s*$", "", title, flags=re.IGNORECASE)
    return title.strip()

def get_channel_from_title(title: str):
    if not title:
        return "(no channel)"
    matches = re.findall(r"\bby\s+([^-\n]+)", title, flags=re.IGNORECASE)
    return matches[-1].strip() if matches else "(no channel)"

def get_views(page):
    try:
        txt = page.inner_text("body")
        m = re.search(r"([\d,]+)\s+Views", txt, re.IGNORECASE)
        return m.group(1).strip() if m else "N/A"
    except Exception:
        return "N/A"

def get_preview_image(page):
    try:
        img = page.evaluate("() => document.querySelector(\"meta[property='og:image']\")?.content || ''")
        if img:
            return img
    except Exception:
        pass
    try:
        img = page.evaluate("() => document.querySelector(\"meta[name='twitter:image']\")?.content || ''")
        if img:
            return img
    except Exception:
        pass
    try:
        img = page.evaluate("""
        () => {
          const imgs = Array.from(document.querySelectorAll("img"))
            .map(i => i.getAttribute("src") || "")
            .filter(src => src.includes("media") || src.includes("giphy"));
          return imgs.length ? imgs[0] : "";
        }
        """)
        return img or ""
    except Exception:
        return ""


# -----------------------------
# ✅ Smart Recommended Tag Builder
# -----------------------------
def build_recommended_tags(results, suggested_tags, top_n=20):
    """
    Combines:
    - competitor tags from extracted results
    - suggested tags
    - frequency analysis across all results
    Removes duplicates and returns top N best tags.
    """

    all_tags = []
    for r in results:
        all_tags.extend(r.get("tags", []))

    # frequency count
    freq = {}
    for t in all_tags:
        freq[t] = freq.get(t, 0) + 1

    # scoring
    scores = {}
    for tag, count in freq.items():
        scores[tag] = float(count)

    # bonus for suggested tags
    for tag in suggested_tags:
        if tag in scores:
            scores[tag] += 2.0
        else:
            scores[tag] = 1.5

    # sort by score desc
    sorted_tags = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    recommended = [t for t, _ in sorted_tags]
    recommended = unique_order(recommended)

    return recommended[:top_n]

# -----------------------------
# Extract tags cluster + click ...
# -----------------------------
def extract_tag_chip_cluster(page):
    data = page.evaluate("""
    () => {
      const bad = [
        "copy link","download","favorite","embed","report","share","views","open on giphy",
        "related","more like this",
        "gifs","stickers","clips",
        "manage cookies","cookies","cookie","agree","reject","accept",
        "privacy","terms","settings",
        "sign up","log in","login","signup",
        "upload","create","browse","developers","apps"
      ];

      const els = Array.from(document.querySelectorAll("a, button, span, div"));

      const chips = els.map(e => {
        const txt = (e.innerText || "").trim();
        const r = e.getBoundingClientRect();
        return { txt, x:r.left, y:r.top, w:r.width, h:r.height };
      })
      .filter(o => o.txt && o.txt.length >= 1 && o.txt.length <= 35)
      .filter(o => o.w >= 25 && o.w <= 280 && o.h >= 16 && o.h <= 80)
      .filter(o => !bad.some(b => o.txt.toLowerCase().includes(b)));

      if (!chips.length) return { tags: [], hasMore: false };

      chips.sort((a,b)=>a.y-b.y);

      const clusters = [];
      let current = [];
      for (const c of chips) {
        if (!current.length) { current=[c]; continue; }
        if (Math.abs(c.y - current[current.length-1].y) < 90) current.push(c);
        else { clusters.push(current); current=[c]; }
      }
      if (current.length) clusters.push(current);

      function scoreCluster(cluster) {
        const s = new Set(cluster.map(o => o.txt.toLowerCase().trim()));
        return s.size;
      }

      clusters.sort((a,b)=>scoreCluster(b)-scoreCluster(a));
      const best = clusters[0] || [];

      const seen = new Set();
      const tags = [];
      for (const b of best) {
        const k = b.txt.toLowerCase().trim();
        if (seen.has(k)) continue;
        seen.add(k);
        tags.push(b.txt);
      }

      const hasMore = tags.includes("...") || tags.includes("…");
      return { tags, hasMore };
    }
    """)
    return data.get("tags", []), data.get("hasMore", False)

def click_more_chip_if_present(page):
    for t in ["...", "…"]:
        loc = page.locator(f"text={t}").first
        try:
            if loc.count() > 0:
                loc.click(timeout=2000)
                return True
        except Exception:
            pass
    return False

# -----------------------------
# Browser launch helper (stable)
# -----------------------------
def launch_browser(pw):
    return pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote",
            "--single-process",
        ],
    )

# -----------------------------
# Suggestion Scraper (NO API)
# -----------------------------
def scrape_search_suggestions(keyword: str):
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    search_url = f"https://giphy.com/search/{keyword.replace(' ', '-')}"
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        page = browser.new_page()
        page.goto(search_url, wait_until="networkidle", timeout=70000)
        page.wait_for_timeout(1500)

        suggested = page.evaluate("""
        () => {
          const bad = ["gifs","stickers","clips"];
          const chips = Array.from(document.querySelectorAll("a[href^='/search/']"))
            .map(a => (a.innerText || '').trim())
            .filter(t => t && t.length > 1 && t.length <= 35)
            .filter(t => !bad.includes(t.toLowerCase().trim()));
          return chips;
        }
        """)
        browser.close()

    suggested = unique_order(suggested)
    return unique_order([normalize_tag(t) for t in suggested if t])[:40]

# -----------------------------
# GIF extractor
# -----------------------------
def extract_giphy_info(url: str):
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        page = browser.new_page()

        page.goto(url, wait_until="networkidle", timeout=70000)
        page.wait_for_timeout(1500)

        raw_title = page.title()
        title = clean_title(raw_title)
        channel = get_channel_from_title(raw_title)
        views = get_views(page)
        preview = get_preview_image(page)

        page.mouse.wheel(0, 4200)
        page.wait_for_timeout(1800)

        tags_before, has_more = extract_tag_chip_cluster(page)

        if has_more:
            click_more_chip_if_present(page)
            page.wait_for_timeout(1800)

        tags_after, _ = extract_tag_chip_cluster(page)

        browser.close()

        tags_after = unique_order([t for t in tags_after if t and t.strip() and t.strip() not in ["...", "…"]])
        tags = unique_order([normalize_tag(t) for t in tags_after if normalize_tag(t)])

        return {
            "title": title,
            "channel": channel,
            "views": views,
            "preview": preview,
            "tags": tags,
            "url": url
        }

# -----------------------------
# Header
# -----------------------------
st.markdown("<div class='main-title'>✨ GIPHY Tag Extractor Tool</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-title'>Extract tags from GIF links and get extra tag suggestions from GIPHY search.</div>", unsafe_allow_html=True)

# -----------------------------
# Input Panel
# -----------------------------
st.markdown("<div class='panel'>", unsafe_allow_html=True)

st.session_state.gif_links = st.text_area(
    "📌 Paste multiple GIPHY links (one per line)",
    height=170,
    value=st.session_state.gif_links
)

st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

col1, col2 = st.columns([4, 1])

with col1:
    st.session_state.keyword = st.text_input(
        "💡 Enter keyword for suggestions (birthday, love, new year)",
        value=st.session_state.keyword
    )

with col2:
    st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
    run_suggest = st.button("💡 Get Suggested Tags", use_container_width=True)

st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

run_extract = st.button("🚀 Extract Tags from GIF Links", type="primary")

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<div class='panel'>", unsafe_allow_html=True)

# -----------------------------
# Actions
# -----------------------------
urls = [u.strip() for u in st.session_state.gif_links.split("\n") if u.strip()]

if run_extract:
    if not urls:
        st.error("Please paste at least one GIPHY link.")
    else:
        results = []
        all_sets = []
        progress = st.progress(0)

        for i, url in enumerate(urls):
            with st.spinner(f"Processing {i+1}/{len(urls)}..."):
                info = extract_giphy_info(url)
                results.append(info)
                all_sets.append(set(info["tags"]))
            progress.progress(int(((i+1)/len(urls))*100))

        st.session_state.results = results
        st.session_state.common_tags = sorted(list(set.intersection(*all_sets))) if all_sets else []

        # reset compare selections after new extraction
        st.session_state.compare_selected = []
        st.session_state.compare_select_all = False

if run_suggest:
    if not st.session_state.keyword.strip():
        st.error("Enter a keyword first.")
    else:
        with st.spinner("Searching suggested tags on GIPHY..."):
            st.session_state.suggested_tags = scrape_search_suggestions(st.session_state.keyword)

# -----------------------------
# Display: Common Tags (ALL GIFS)
# -----------------------------
if st.session_state.common_tags:
    common_no_hash = [strip_hash(t) for t in st.session_state.common_tags]
    st.markdown("<div class='section-title'>✅ Common Tags (Used in ALL GIFs)</div>", unsafe_allow_html=True)
    # st.markdown("<div class='flex-wrap'>", unsafe_allow_html=True)
    st.markdown("".join([f"<span class='common-chip'>{t}</span>" for t in st.session_state.common_tags]), unsafe_allow_html=True)
    # st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='copy-box'>{', '.join(common_no_hash)}</div>", unsafe_allow_html=True)


# -----------------------------
# ✅ Compare Selected GIFs + Common Tags + Tag Frequency (Selected vs All)
# -----------------------------
if st.session_state.results and len(st.session_state.results) > 1:
    st.markdown("---")
    st.markdown("<div style='height:3px;'></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>🔍 Compare Selected GIFs</div>", unsafe_allow_html=True)

    # ✅ Indexed titles for dropdown
    titles = [f"{i+1}. {r['title']}" for i, r in enumerate(st.session_state.results)]

    # ✅ Select all checkbox
    select_all = st.checkbox("Select All GIFs or Compare", value=st.session_state.compare_select_all)
    st.session_state.compare_select_all = select_all

    if select_all:
        selected_titles = titles
    else:
        selected_titles = st.multiselect(
            "Select GIFs to compare",
            options=titles,
            default=st.session_state.compare_selected
        )
        st.session_state.compare_selected = selected_titles

    # Convert selected titles to indexes
    selected_indexes = [titles.index(t) for t in selected_titles] if selected_titles else []

    # ✅ Common tags for selected GIFs
    if len(selected_indexes) >= 2:
        selected_sets = [set(st.session_state.results[i]["tags"]) for i in selected_indexes]
        common_selected = sorted(list(set.intersection(*selected_sets)))

        if common_selected:
            st.success(f"✅ {len(common_selected)} common tags found among selected GIFs")

            # st.markdown("<div class='flex-wrap'>", unsafe_allow_html=True)
            st.markdown("".join([f"<span class='common-chip'>{t}</span>" for t in common_selected]), unsafe_allow_html=True)
            # st.markdown("</div>", unsafe_allow_html=True)

            common_selected_no_hash = [strip_hash(t) for t in common_selected]
            st.markdown(f"<div class='copy-box'>{', '.join(common_selected_no_hash)}</div>", unsafe_allow_html=True)
        else:
            st.warning("No common tags found among selected GIFs.")
    else:
        st.info("Select at least 2 GIFs to see common tags between them.")

    # -----------------------------
    # ✅ Tag Frequency Toggle
    # -----------------------------
    # st.markdown("---")
    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-title2'>📊 Tag Frequency</div>", unsafe_allow_html=True)
    # Toggle
    mode = st.radio("Check tag frequency (How many GIFs use each tag).",["Selected GIFs", "All GIFs"],horizontal=True)

    # Decide which set to use
    if mode == "All GIFs":
        indexes_for_freq = list(range(len(st.session_state.results)))
    else:
        indexes_for_freq = selected_indexes

    if not indexes_for_freq:
        st.warning("Select GIFs first to view frequency in Selected mode.")
    else:
        # Build frequency dictionary
        freq = {}
        for i in indexes_for_freq:
            for tag in st.session_state.results[i]["tags"]:
                freq[tag] = freq.get(tag, 0) + 1

        total = len(indexes_for_freq)
        freq_sorted = sorted(freq.items(), key=lambda x: x[1], reverse=True)

        # ✅ Horizontal chips (wrap)
        # st.markdown("<div class='flex-wrap'>", unsafe_allow_html=True)
        for tag, count in freq_sorted[:80]:
            chips_html = "".join([
                f"<span class='tag-chip'>{tag} <b style='color:#111827;'>({count}/{total})</b></span>"
                for tag, count in freq_sorted[:80]
            ])
        st.markdown(f"<div class='flex-wrap'>{chips_html}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Copy box without #
        copy_list = [f"{strip_hash(tag)} ({count}/{total})" for tag, count in freq_sorted]
        st.markdown(f"<div class='copy-box'>{', '.join(copy_list)}</div>", unsafe_allow_html=True)
        st.markdown("---")



# -----------------------------
# Display: Suggested Tags
# -----------------------------
if st.session_state.suggested_tags:
    # st.markdown("<div style='height:25px;'></div>", unsafe_allow_html=True)
    suggested_no_hash = [strip_hash(t) for t in st.session_state.suggested_tags]
    st.markdown("<div class='section-title'>💡 Suggested Tags from GIPHY Search</div>", unsafe_allow_html=True)
    st.markdown("<div class='flex-wrap'>", unsafe_allow_html=True)
    st.markdown("".join([f"<span class='tag-chip'>{t}</span>" for t in st.session_state.suggested_tags]), unsafe_allow_html=True)
    # st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='copy-box'>{', '.join(suggested_no_hash)}</div>", unsafe_allow_html=True)
    st.markdown("---")

# -----------------------------
# ✅ Recommended Tags (Top 20)
# -----------------------------
if st.session_state.results:
    st.markdown("<div class='section-title'>🎯 Recommended Tags (Top 20)</div>", unsafe_allow_html=True)
    st.caption("Combines competitor tags + suggested tags + frequency analysis and removes duplicates.")
    colR1, colR2 = st.columns([1, 2])

    with colR1:
        run_recommend = st.button("⚡ Generate Recommended Tags", type='primary', use_container_width=True)

    with colR2:
        st.caption("")



    if run_recommend:
        st.session_state.recommended_tags = build_recommended_tags(
            st.session_state.results,
            st.session_state.suggested_tags,
            top_n=20
        )

if st.session_state.recommended_tags:
    rec_tags = st.session_state.recommended_tags
    rec_no_hash = [strip_hash(t) for t in rec_tags]

    chips_html = "".join([f"<span class='common-chip'>{t}</span>" for t in rec_tags])
    st.markdown(f"<div class='flex-wrap'>{chips_html}</div>", unsafe_allow_html=True)

    st.markdown(f"<div class='copy-box'>{', '.join(rec_no_hash)}</div>", unsafe_allow_html=True)
    st.markdown("---")

# -----------------------------
# Display: Results per GIF
# -----------------------------
if st.session_state.results:
    # st.markdown("<div style='height:25px;'></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>📌 Results Per GIF</div>", unsafe_allow_html=True)
    st.markdown("<div style='height:25px;'></div>", unsafe_allow_html=True)

    for idx, item in enumerate(st.session_state.results, start=1):
        col1, col2 = st.columns([1, 2])

        with col1:
            if item["preview"]:
                st.image(item["preview"], width=240)
            else:
                st.warning("No preview found.")

        with col2:
            st.markdown(
                f"<a class='title-link' href='{item['url']}' target='_blank'>{idx}. {item['title']}</a>",
                unsafe_allow_html=True
            )

            st.markdown(
                f"<span class='badge badge-blue'>{item['channel']}</span>"
                f"<span class='badge badge-green'>{item['views']} Views</span>"
                f"<span class='badge badge-purple'>{len(item['tags'])} Tags</span>",
                unsafe_allow_html=True
            )
            # st.markdown("#### Tags")
            if item["tags"]:
                st.markdown("".join([f"<span class='tag-chip'>{t}</span>" for t in item["tags"]]), unsafe_allow_html=True)
            else:
                st.warning("No tags found.")

        st.markdown("---")
