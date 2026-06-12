import streamlit as st
import json
import pandas as pd
import re
import base64
import os
from urllib.parse import urlparse, parse_qs, unquote, quote

st.set_page_config(page_title="GA360 Detector", page_icon="🕵️‍♂️", layout="wide")

# ==========================================
# DICTIONARY (ENGLISH ONLY)
# ==========================================
t = {
    "sidebar_mode": "**Operation Mode: Bulk HAR Analysis (Upload)**",
    "sidebar_version": "Version: 40",
    "sidebar_changelog": """
**🔄 What's new in version 40?**
* **Critical Stability Fix:** Applied `width='stretch'` to `st.dataframe` to prevent ASGI exceptions in Streamlit 1.45+.
* **Data Purity:** Removed the injected metadata row from the DataFrame. The table is now 100% clean data, enabling native Pandas sorting and typing.
* **Error Handling:** Added `try/except` for JSON parsing to prevent unhandled crashes on malformed LLM/engine outputs.
* **Logic Safeties:** Added fallback variables and implemented modulo 100 logic for the cache clearer.
""",
    "title": "GA360 Detector",
    "tabs": ["🚀 Scan Panel", "📚 Knowledge Base (EDU)", "📥 .HAR File Guide"],
    "upload_desc": "Export `.har` files from your browser and upload them below. **You can drag and drop multiple files at once.**",
    "upload_warning": "⚠️ **Pro-tip:** To prevent server timeouts, ensure your `.har` files are under 200MB. Check the instruction tab to learn how to generate lightweight logs.",
    "btn_clear_files": "🗑️ Clear uploaded files",
    "upload_label": "Choose .har files",
    "btn_analyze": "🔍 Analyze Uploaded Files",
    "spinner_msg": "Analyzing file: {}...",
    "expander_title": "{} - Analysis Result (File: {})",
    "err_no_scripts": "No analytics scripts or footprints were found in this HAR file. Ensure the file was recorded correctly.",
    "err_read_file": "Error reading file {}: {}",
    "warn_no_files": "Please upload at least one .har file first.",
    "table_detailed_title": "📊 Detailed Analysis Report (Bulk Export)",
    "btn_download_csv_detailed": "📥 Download CSV Report",
    "expander_copy": "📋 1-Click Copy to Clipboard (Paste directly to Excel/Google Sheets)",
    "csv_filename_detailed": "Report_GA360_Detector.csv",
    "csv_err_msg": "No network events.",
    "csv_col_domain": "Domain (from file)",
    "csv_col_verdict": "Final Verdict",
    "csv_col_confidence": "Verdict Confidence",
    "csv_col_tid": "Property ID (TID)",
    "csv_col_other": "Other Analytics System",
    "csv_col_reason": "Key Rationale",
    "md_domain": "DOMAIN / WEBSITE",
    "md_verdict": "VERDICT",
    "md_confidence": "VERDICT CONFIDENCE",
    "md_other": "OTHER ANALYTICS SYSTEM",
    "md_tids": "Detected Measurement IDs (tid)",
    "table_header_status": "Status",
    "table_header_type": "Rule Type",
    "table_header_rule": "Validation Rule / Limit",
    "table_header_result": "Network Analysis Result",
    "rule_t1_type": "Hard rule #1 (Event Limit)",
    "rule_t1_desc": "Number of custom parameters > 25 in a single event",
    "rule_t1_res": "Max detected: {}",
    "rule_t2_type": "Hard rule #2 (Size Limit)",
    "rule_t2_desc": "Custom dimension string value length > 100 characters",
    "rule_t2_res": "Longest custom value: {} chars",
    "rule_t3_type": "Hard rule #3 (User Limit)",
    "rule_t3_desc": "Registered User Properties in a hit > 25",
    "rule_t3_res": "Max detected: {}",
    "rule_t4_type": "Hard rule #4 (Product Limit)",
    "rule_t4_desc": "Custom item-scoped dimensions per product > 10",
    "rule_t4_res": "Max detected: {} in a single product",
    "rule_m5_type": "Contextual rule #1 (Data Density)",
    "rule_m5_desc": "Total unique ep.* parameters in session > 50",
    "rule_m5_res": "Total detected: {} unique",
    "rule_m6_type": "Contextual rule #2 (IT Architecture)",
    "rule_m6_desc": "Server-Side Tagging (Endpoint in a 1st-party domain)",
    "rule_m6_res": "Collection endpoint detected: {}",
    "rule_m7_type": "Contextual rule #3 (Governance)",
    "rule_m7_desc": "Corporate Multi-tagging setup",
    "rule_m7_res_yes": "Yes ({})",
    "rule_m7_res_no": "No",
    "rule_m8_type": "Contextual rule #4 (Ad Server)",
    "rule_m8_desc": "CM360 specific parameters & paths",
    "rule_m9_type": "Contextual rule #5 (DSP)",
    "rule_m9_desc": "Base Floodlight tags (DV360/GMP)",
    "rule_m9_res_yes": "Yes",
    "rule_m9_res_no": "No",
    "verdict_no_ga": "No Google Analytics",
    "verdict_ga360": "GA 360",
    "verdict_prob_ga360": "Probably GA 360",
    "verdict_free_infra": "Free GA4 (Advanced Infrastructure)",
    "verdict_free_empty": "Free GA4 (Empty Parameters)",
    "verdict_free": "Free GA4",
    "reason_no_ga": "No Google traffic detected. Classification based on competitor market footprints.",
    "reason_pts": "Analysis Score: {}/99 pts (Infra: {}/40 pts, Data_Event: {}/30 pts, Data_Session: {}/29 pts)",
    "har_title": "📥 Guide to Generating Actionable (and Lightweight) .HAR Files",
    "har_subtitle": "Follow this procedure to generate network logs that are rich in analytics data but small enough to avoid server timeout crashes."
}

# --- ZARZĄDZANIE STANEM WIDŻETU (Do przycisku Clear) ---
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# --- PANEL BOCZNY (SIDEBAR) ---
logo_path = "FSE_Logo.png"
if os.path.exists(logo_path):
    st.sidebar.image(logo_path)
else:
    st.sidebar.markdown("<h3 style='text-align: center; color: #888;'>[ LOGO ]</h3>", unsafe_allow_html=True)

st.sidebar.write("")
st.sidebar.markdown(t["sidebar_mode"])
st.sidebar.caption(t["sidebar_version"])
st.sidebar.info(t["sidebar_changelog"])

st.sidebar.markdown(
    """
    <div style="margin-top: 50px; text-align: center; color: #888;">
        <small>© Full Stack Experts 2026</small>
    </div>
    """,
    unsafe_allow_html=True
)

# --- FUNKCJA WSPÓLNA: PANCERNE FILTROWANIE HAR ---
def filtruj_logi_har(har_json):
    filtered_requests = []
    wykryte_inne = set()
    
    alternatywne_systemy = {
        "Adobe Analytics (Enterprise)": ["omtrdc.net", "b/ss", "adobe-analytics", "sc.omtrdc", "insertjs"],
        "Piwik PRO": ["piwik.pro", "containers.piwik.pro", "ppms.js", "ppms.php"],
        "Matomo": ["matomo.php", "matomo.js", "/piwik.php", "/piwik.js", "matomo.cloud"],
        "Amplitude": ["amplitude.com", "api.amplitude.com", "api2.amplitude.com"],
        "Mixpanel": ["mixpanel.com", "api.mixpanel.com", "api-eu.mixpanel.com"],
        "Hotjar": ["hotjar.com", "vars.hotjar.com", "static.hotjar.com"]
    }
    
    for entry in har_json.get("log", {}).get("entries", []):
        original_url = entry.get("request", {}).get("url", "")
        url_lower = original_url.lower()
        
        for system, footprints in alternatywne_systemy.items():
            if any(fp in url_lower for fp in footprints):
                wykryte_inne.add(system)
        
        if not "dcmads.js" in url_lower:
            if any(url_lower.endswith(ext) or f"{ext}?" in url_lower for ext in [".js", ".css", ".woff", ".woff2", ".ttf", ".png", ".jpg", ".svg", ".gif"]):
                continue
        
        is_analytics = False
        if any(x in url_lower for x in ["collect", "google-analytics", "doubleclick", "analytics", "/gtm", "metrics", "stat", "track", "tag", "data", "pagead", "activityi", "fls.", "dcmads"]):
            is_analytics = True
            
        query_string = entry.get("request", {}).get("queryString", [])
        for q in query_string:
            if q.get("name") in ["tid", "v", "en", "dclid"]:
                is_analytics = True
                break

        post_data_obj = entry.get("request", {}).get("postData", {})
        post_text = post_data_obj.get("text", "")
        
        if post_data_obj.get("encoding") == "base64" and post_text:
            try:
                post_text = base64.b64decode(post_text).decode('utf-8')
            except Exception:
                pass

        if not post_text and "params" in post_data_obj:
            reconstructed = []
            for p in post_data_obj["params"]:
                k = p.get("name", "")
                v = p.get("value", "")
                reconstructed.append(f"{quote(k)}={quote(v)}")
            post_text = "&".join(reconstructed)

        if not is_analytics and post_text and ("tid=" in post_text or "en=" in post_text):
            is_analytics = True

        if not is_analytics:
            continue

        filtered_requests.append({
            "url": original_url, 
            "query_string": query_string,
            "post_data": post_text
        })
        
    return filtered_requests, list(wykryte_inne)

# ==========================================
# SILNIK LOKALNEJ ANALIZY (Dynamic Scoring)
# ==========================================
def analizuj_lokalnie(requests_list, czysta_domena, wykryte_inne, t_dict):
    max_ep_per_event = 0
    max_custom_param_len = 0
    max_up_per_event = 0
    max_item_params = 0
    globalne_ep_params = set()
    wykryte_ga4_tids = set()
    wykryte_ads_tids = set()
    server_side_domain = "No"
    pewnosc = "N/A"
    werdykt = "N/A"
    
    gmp_evidence = False
    cm360_ddm = False
    cm360_cost = False
    cm360_qty = False
    cm360_dclid = False
    
    native_excludes = [
        "page_title", "page_location", "page_referrer", "page_path",
        "search_term", "content_group", "campaign", "source", "medium", 
        "term", "content"
    ]
    
    standard_pr_suffixes = {'id', 'nm', 'br', 'ca', 'c2', 'c3', 'c4', 'c5', 'va', 'pr', 'qt', 'cc', 'lp', 'ln', 'li', 'ds', 'af', 'ps'}
    standard_mp_suffixes = {'item_id', 'item_name', 'item_brand', 'item_category', 'item_category2', 'item_category3', 'item_category4', 'item_category5', 'price', 'quantity', 'item_variant', 'promotion_name', 'promotion_id', 'coupon', 'discount', 'index', 'affiliation', 'item_list_name', 'item_list_id'}

    wszystkie_zdarzenia = []

    for req in requests_list:
        original_url = req.get("url", "")
        parsed_url = urlparse(original_url)
        hostname = parsed_url.hostname or ""
        url_lower = original_url.lower()
        
        if czysta_domena != "Unknown domain" and czysta_domena in hostname and not any(x in hostname for x in ["google", "doubleclick", "analytics", "facebook"]):
            server_side_domain = hostname
            
        if any(x in hostname for x in ["doubleclick.net", "fls.doubleclick.net", "ad.doubleclick.net"]) or any(x in url_lower for x in ["g.doubleclick", "/ddm/activity/", "/activityi", "/pagead/", "dc_pre="]):
            gmp_evidence = True
            
        if any(x in url_lower for x in ["/ddm/", "dcmads.js"]):
            cm360_ddm = True
            
        if "dclid=" in url_lower:
            cm360_dclid = True
            
        base_params = {}
        for q in req.get("query_string", []):
            name = q.get("name")
            value = q.get("value", "")
            if name: base_params[name] = value
            if name and name.lower() == "dclid":
                cm360_dclid = True

        post_text = req.get("post_data", "")
        if post_text:
            for line in post_text.splitlines():
                line = line.strip()
                if not line: continue
                
                event_params = base_params.copy()
                parsed_success = False
                
                try:
                    parsed_post = parse_qs(line, keep_blank_values=False)
                    if parsed_post:
                        for k, v in parsed_post.items():
                            if v: event_params[k] = v[0]
                        parsed_success = True
                except Exception:
                    pass
                
                if not parsed_success:
                    for match in re.findall(r'([a-zA-Z0-9_\.\-]+)=([^&\s;]+)', line):
                        event_params[match[0]] = match[1]
                    
                wszystkie_zdarzenia.append({"url": original_url, "params": event_params})
        else:
            if base_params:
                wszystkie_zdarzenia.append({"url": original_url, "params": base_params})

    for event in wszystkie_zdarzenia:
        params = event["params"]
        original_url = event["url"]
        url_lower = original_url.lower()
        
        if any(x in url_lower for x in ["doubleclick.net", "/activityi", "/ddm/"]):
            if "cost" in params:
                cm360_cost = True
            if "qty" in params:
                cm360_qty = True
        
        if "tid" in params and params["tid"]:
            tid_val = str(params["tid"]).upper()
            if tid_val.startswith("G-"):
                wykryte_ga4_tids.add(tid_val)
            elif tid_val.startswith("AW-") or tid_val.startswith("DC-"):
                wykryte_ads_tids.add(tid_val)
        else:
            tid_match_ga4 = re.search(r'tid=(G-[A-Z0-9]+)', original_url, re.IGNORECASE)
            if tid_match_ga4: 
                wykryte_ga4_tids.add(tid_match_ga4.group(1).upper())
                
            tid_match_aw = re.search(r'tid=((?:AW|DC)-[A-Z0-9\-]+)', original_url, re.IGNORECASE)
            if tid_match_aw:
                wykryte_ads_tids.add(tid_match_aw.group(1).upper())

        current_event_ep_count = 0
        current_event_up_count = 0
        custom_item_params_per_product = {}
        
        for k, v in params.items():
            val_str = unquote(str(v))
            
            if k.startswith("ep.") or k.startswith("epn."):
                current_event_ep_count += 1
                param_name_clean = k.replace("ep.", "").replace("epn.", "")
                globalne_ep_params.add(param_name_clean)
                
                if param_name_clean not in native_excludes:
                    max_custom_param_len = max(max_custom_param_len, len(val_str))
                    
            elif k.startswith("up.") or k.startswith("upn."):
                current_event_up_count += 1
                
            match_pr = re.match(r'^(?:pr|pi)(\d+)(.+)', k)
            if match_pr:
                product_idx = match_pr.group(1)
                suffix = match_pr.group(2)
                if suffix not in standard_pr_suffixes:
                    if product_idx not in custom_item_params_per_product:
                        custom_item_params_per_product[product_idx] = set()
                    custom_item_params_per_product[product_idx].add(suffix)
            else:
                match_items_dot = re.match(r'^items\.(\d+)\.(.+)', k)
                if match_items_dot:
                    product_idx = match_items_dot.group(1)
                    suffix = match_items_dot.group(2)
                    if suffix not in standard_mp_suffixes:
                        if product_idx not in custom_item_params_per_product:
                            custom_item_params_per_product[product_idx] = set()
                        custom_item_params_per_product[product_idx].add(suffix)

        max_ep_per_event = max(max_ep_per_event, current_event_ep_count)
        max_up_per_event = max(max_up_per_event, current_event_up_count)
        if custom_item_params_per_product:
            current_max_items = max(len(v) for v in custom_item_params_per_product.values())
            max_item_params = max(max_item_params, current_max_items)

    r1 = "[✅]" if max_ep_per_event > 25 else "[❌]"
    r2 = "[✅]" if max_custom_param_len > 100 else "[❌]"
    r3 = "[✅]" if max_up_per_event > 25 else "[❌]"
    r4 = "[✅]" if max_item_params > 10 else "[❌]"
    
    r5 = "[✅]" if len(globalne_ep_params) > 50 else "[❌]"
    r6 = "[✅]" if server_side_domain != "No" else "[❌]"
    r7 = "[✅]" if len(wykryte_ga4_tids) > 1 else "[❌]"
    
    cm360_evidence = cm360_ddm or cm360_cost or cm360_qty or cm360_dclid
    r8 = "[✅]" if cm360_evidence else "[❌]"
    r9 = "[✅]" if gmp_evidence else "[❌]"
    
    cm360_ddm_str = "Yes" if cm360_ddm else "No"
    cm360_cost_str = "Yes" if cm360_cost else "No"
    cm360_qty_str = "Yes" if cm360_qty else "No"
    cm360_dclid_str = "Yes" if cm360_dclid else "No"
    
    cm360_szczegoly_md = f"**/ddm/:** {cm360_ddm_str}, **cost:** {cm360_cost_str}, **qty:** {cm360_qty_str}, **dclid:** {cm360_dclid_str}"
    cm360_szczegoly_clean = f"/ddm/: {cm360_ddm_str}, cost: {cm360_cost_str}, qty: {cm360_qty_str}, dclid: {cm360_dclid_str}"
    
    twarda_regula_zlamana = (r1 == "[✅]" or r2 == "[✅]" or r3 == "[✅]" or r4 == "[✅]")
    puste_zdarzenia_ga4 = (max_ep_per_event == 0 and max_item_params == 0 and len(globalne_ep_params) == 0)

    # --- MATEMATYKA (DYNAMIC SCORING) ---
    infra_score = 0
    if r6 == "[✅]": infra_score += 10
    if r7 == "[✅]": infra_score += 10
    
    if cm360_evidence:
        infra_score += 20
    elif gmp_evidence:
        infra_score += 10
    
    data_score_ep = int(min((max_ep_per_event / 25) * 30, 30))
    data_score_gl = int(min((len(globalne_ep_params) / 50) * 29, 29))
    
    total_score = infra_score + data_score_ep + data_score_gl

    if len(wykryte_ga4_tids) == 0:
        werdykt = t_dict["verdict_no_ga"]
        uzasadnienie_tekst = t_dict["reason_no_ga"]
        if wykryte_inne:
            if "Adobe Analytics (Enterprise)" in wykryte_inne:
                pewnosc = "100%"
            else:
                pewnosc = "95%"
        else:
            pewnosc = "90%"
    else:
        uzasadnienie_tekst = t_dict["reason_pts"].format(total_score, infra_score, data_score_ep, data_score_gl)
        
        if twarda_regula_zlamana:
            werdykt = t_dict["verdict_ga360"]
            pewnosc = "100%"
        elif total_score >= 60:
            werdykt = t_dict["verdict_prob_ga360"]
            pewnosc = f"{total_score}%"
        elif infra_score >= 20 and total_score < 60:
            werdykt = t_dict["verdict_free_infra"]
            pewnosc = f"{100 - total_score}%"
        elif puste_zdarzenia_ga4:
            werdykt = t_dict["verdict_free_empty"]
            pewnosc = "95%"
        else:
            werdykt = t_dict["verdict_free"]
            pewnosc = f"{100 - total_score}%"

    tid_ga4_display = ", ".join(list(wykryte_ga4_tids)) if wykryte_ga4_tids else t_dict["verdict_no_ga"]
    inny_system_display = f"Yes, {', '.join(wykryte_inne)}" if wykryte_inne else "No"

    markdown_output = f"""
* **{t_dict['md_domain']}:** `{czysta_domena}`
* **{t_dict['md_verdict']}:** **{werdykt}**
* **{t_dict['md_confidence']}:** `{pewnosc}`
* **{t_dict['md_other']}:** `{inny_system_display}`
* **{t_dict['md_tids']}:** `{tid_ga4_display}`

---
### 📋 Rule Validation Summary

| {t_dict['table_header_status']} | {t_dict['table_header_type']} | {t_dict['table_header_rule']} | {t_dict['table_header_result']} |
| :---: | :--- | :--- | :--- |
| {r1} | {t_dict['rule_t1_type']} | {t_dict['rule_t1_desc']} | {t_dict['rule_t1_res'].format(max_ep_per_event)} |
| {r2} | {t_dict['rule_t2_type']} | {t_dict['rule_t2_desc']} | {t_dict['rule_t2_res'].format(max_custom_param_len)} |
| {r3} | {t_dict['rule_t3_type']} | {t_dict['rule_t3_desc']} | {t_dict['rule_t3_res'].format(max_up_per_event)} |
| {r4} | {t_dict['rule_t4_type']} | {t_dict['rule_t4_desc']} | {t_dict['rule_t4_res'].format(max_item_params)} |
| {r5} | {t_dict['rule_m5_type']} | {t_dict['rule_m5_desc']} | {t_dict['rule_m5_res'].format(len(globalne_ep_params))} |
| {r6} | {t_dict['rule_m6_type']} | {t_dict['rule_m6_desc']} | {t_dict['rule_m6_res'].format(server_side_domain)} |
| {r7} | {t_dict['rule_m7_type']} | {t_dict['rule_m7_desc']} | {t_dict['rule_m7_res_yes'].format(len(wykryte_ga4_tids)) if len(wykryte_ga4_tids)>1 else t_dict['rule_m7_res_no']} |
| {r8} | {t_dict['rule_m8_type']} | {t_dict['rule_m8_desc']} | {cm360_szczegoly_md} |
| {r9} | {t_dict['rule_m9_type']} | {t_dict['rule_m9_desc']} | {t_dict['rule_m9_res_yes'] if gmp_evidence else t_dict['rule_m9_res_no']} |
"""
    json_payload = {
        "verdict": werdykt,
        "confidence": pewnosc,
        "tid": tid_ga4_display,
        "other_systems_text": inny_system_display,
        "reason": uzasadnienie_tekst,
        "rules": {
            "r1": r1,
            "r2": r2,
            "r3": r3,
            "r4": r4,
            "r5": r5,
            "r6": r6,
            "r7": r7,
            "r8": r8,
            "r9": r9
        }
    }
    
    json_str = json.dumps(json_payload, indent=2)
    ticks = "`" * 3
    return f"{markdown_output}\n{ticks}json\n{json_str}\n{ticks}"

# ==========================================
# INTERFEJS UŻYTKOWNIKA
# ==========================================
st.title(f"🕵️‍♂️ {t['title']}")

tab1, tab2, tab3 = st.tabs(t["tabs"])

with tab1:
    detailed_data_rows = []

    col_desc, col_clear = st.columns([4, 1])
    with col_desc:
        st.markdown(t["upload_desc"])
        st.caption(t["upload_warning"])
    with col_clear:
        if st.button(t["btn_clear_files"]):
            st.session_state.uploader_key = (st.session_state.uploader_key + 1) % 100
            st.rerun()

    wgrane_pliki = st.file_uploader(
        t["upload_label"], 
        type=["har"], 
        accept_multiple_files=True, 
        key=f"uploader_{st.session_state.uploader_key}"
    )
    
    if st.button(t["btn_analyze"]):
        if wgrane_pliki:
            for plik in wgrane_pliki:
                with st.spinner(t["spinner_msg"].format(plik.name)):
                    try:
                        har_data = json.load(plik)
                        
                        czysta_domena = plik.name.replace(".har", "")
                        try:
                            if "pages" in har_data.get("log", {}) and len(har_data["log"]["pages"]) > 0:
                                pierwsza_strona = har_data["log"]["pages"][0].get("title", "")
                                if pierwsza_strona.startswith("http"):
                                    parsed = urlparse(pierwsza_strona)
                                    czysta_domena = parsed.hostname.replace("www.", "")
                        except Exception:
                            pass

                        filtered_requests, wykryte_inne = filtruj_logi_har(har_data)
                        
                        with st.expander(t["expander_title"].format(czysta_domena, plik.name), expanded=False):
                            if not filtered_requests and not wykryte_inne:
                                st.warning(t["err_no_scripts"])
                                
                                detailed_err = {
                                    t["csv_col_domain"]: czysta_domena,
                                    t["csv_col_verdict"]: "Error",
                                    t["csv_col_confidence"]: "0%",
                                    t["csv_col_other"]: "No",
                                    t["csv_col_tid"]: "None",
                                    t["csv_col_reason"]: t["csv_err_msg"]
                                }
                                
                                for rule_key in [t["rule_t1_type"], t["rule_t2_type"], t["rule_t3_type"], t["rule_t4_type"], t["rule_m5_type"], t["rule_m6_type"], t["rule_m7_type"], t["rule_m8_type"], t["rule_m9_type"]]:
                                    detailed_err[rule_key] = "-"
                                detailed_data_rows.append(detailed_err)

                            else:
                                response_text = analizuj_lokalnie(filtered_requests, czysta_domena, wykryte_inne, t)
                                
                                ticks = "`" * 3
                                parts = response_text.split(f"{ticks}json")
                                st.markdown(parts[0])
                                
                                if len(parts) > 1:
                                    try:
                                        extracted_json = json.loads(parts[1].split(ticks)[0].strip())
                                    except json.JSONDecodeError as e:
                                        st.error(f"JSON Parsing Error for {czysta_domena}: {e}")
                                        extracted_json = {
                                            "verdict": "Error",
                                            "confidence": "N/A",
                                            "tid": "None",
                                            "other_systems_text": "N/A",
                                            "reason": "Engine output parsing failure",
                                            "rules": {}
                                        }
                                        
                                    detailed_row = {
                                        t["csv_col_domain"]: czysta_domena,
                                        t["csv_col_verdict"]: extracted_json.get("verdict", "N/A"),
                                        t["csv_col_confidence"]: extracted_json.get("confidence", "N/A"),
                                        t["csv_col_other"]: extracted_json.get("other_systems_text", "N/A"),
                                        t["csv_col_tid"]: extracted_json.get("tid", "N/A"),
                                        t["csv_col_reason"]: extracted_json.get("reason", "N/A")
                                    }
                                    
                                    rules_obj = extracted_json.get("rules", {})
                                    detailed_row[t["rule_t1_type"]] = rules_obj.get("r1", "-")
                                    detailed_row[t["rule_t2_type"]] = rules_obj.get("r2", "-")
                                    detailed_row[t["rule_t3_type"]] = rules_obj.get("r3", "-")
                                    detailed_row[t["rule_t4_type"]] = rules_obj.get("r4", "-")
                                    detailed_row[t["rule_m5_type"]] = rules_obj.get("r5", "-")
                                    detailed_row[t["rule_m6_type"]] = rules_obj.get("r6", "-")
                                    detailed_row[t["rule_m7_type"]] = rules_obj.get("r7", "-")
                                    detailed_row[t["rule_m8_type"]] = rules_obj.get("r8", "-")
                                    detailed_row[t["rule_m9_type"]] = rules_obj.get("r9", "-")
                                    
                                    detailed_data_rows.append(detailed_row)
                    except Exception as e:
                        st.error(t["err_read_file"].format(plik.name, e))
        else:
            st.warning(t["warn_no_files"])

    if detailed_data_rows:
        st.write("---")
        st.subheader(t["table_detailed_title"])
        
        detailed_data_rows.sort(key=lambda x: str(x.get(t["csv_col_domain"], "")).lower())
        
        df_detailed = pd.DataFrame(detailed_data_rows)
        st.dataframe(df_detailed, width='stretch')
        
        csv_detailed = df_detailed.to_csv(index=False, sep=';', encoding='utf-8-sig')
        
        st.download_button(
            label=t["btn_download_csv_detailed"],
            data=csv_detailed,
            file_name=t["csv_filename_detailed"],
            mime="text/csv"
        )
        
        tsv_detailed = df_detailed.to_csv(index=False, sep='\t')
        with st.expander(t["expander_copy"]):
            st.code(tsv_detailed, language="text")

with tab2:
    st.title("📚 Analytics & Business Knowledge Base")
    st.markdown("Logical documentation of the rules embedded directly within the detective's verification engine.")
    
    st.subheader("🔴 Hard Rules and Prohibitive Limits (100% Confidence)")
    with st.expander("Hard rule #1: Number of custom parameters in an event (>25)"):
        st.markdown("* **Technical Background:** Free GA4 applies a strict limit of **25 custom parameters** per event. The corporate **GA360 license raises this limit to 100**.\n* **Detection Logic:** The script counts unique parameters prefixed with `ep.` and `epn.`. Exceeding 25 is irrefutable proof of a premium license.")
    with st.expander("Hard rule #2: Maximum parameter value length (>100 characters)"):
        st.markdown("* **Technical Background:** Standard GA4 automatically truncates Custom Dimension string values if they exceed **100 characters**. **GA360 allows strings up to 500 characters**.\n* **Detection Logic:** The engine measures the length of custom parameters. Capturing a value >100 characters automatically confirms a GA360 setup.")
    with st.expander("Hard rule #3: Number of User Properties (>25)"):
        st.markdown("* **Technical Background:** Free GA4 allows a maximum of **25 User Properties**. The **GA360 service expands this threshold to 100**.\n* **Detection Logic:** We filter for `up.` and `upn.` parameters. Exceeding 25 unique properties triggers the hard verdict.")
    with st.expander("Hard rule #4: Custom item-scoped dimensions per product (>10)"):
        st.markdown("* **Technical Background:** In free GA4, you can append a maximum of **10 custom dimensions** to each item in the `items` array. **GA360 expands this limit to 27**.\n* **Detection Logic:** The system uses a strict whitelist approach. If a product array contains any parameter that is *not* a standard GA4 property (like id, name, price, brand), it is dynamically flagged as custom. If a single product contains more than 10 such attributes, the system triggers a hard GA360 verdict.")
    
    st.write("")
    st.subheader("🟡 Dynamic Contextual Scoring (Data Density Analysis)")
    with st.expander("How to read Confidence vs Score Points? (Decoding Manual)"):
        st.markdown("The system distinguishes between **Verdict Confidence (%)** and **Analysis Points (max 99 pts)**. Breakdown:\n\n* **Infra (max 40 pts):** Infrastructure evaluation. Awards 10 pts for Server-Side Tagging, 10 pts for Multi-tagging, and **20 pts for Campaign Manager 360** detection (or 10 pts for standard DV360).\n* **Data_Event (max 30 pts):** Evaluates the weight of the single heaviest network hit.\n* **Data_Session (max 29 pts):** Total vocabulary size (rewards properties exceeding 50 unique session parameters).")
    with st.expander("Ad Server Detection: Campaign Manager 360 vs DV360"):
        st.markdown("* **Footprint 1 (Click Identifier):** The presence of a `dclid=` parameter is proof of an entry via a CM360 ad.\n* **Footprint 2 (DDM Paths):** `/ddm/` paths and `dcmads.js` scripts inside DoubleClick network requests.\n* **Footprint 3 (Native E-commerce parameters):** CM360 sales tags utilize built-in `cost=` and `qty=` parameters. Standard DV360 usually collects this via custom variables like `u1=`.\n* **Business Impact:** Detecting CM360 awards double infrastructure points. It signals huge media budgets and enterprise readiness.")

with tab3:
    st.title(t["har_title"])
    st.markdown(t["har_subtitle"])
    
    st.markdown("""
    ### 🛠️ Step-by-Step Instructions for Consultants and Sales Teams:
    
    #### 0️⃣ Step 0: CRITICAL PRE-REQUISITE (Filter out media)
    * Open DevTools (`F12`) and navigate to the **Network** tab.
    * Click the **Filter** icon (looks like a funnel) and select **`Fetch/XHR`** (or block `Img` and `Media`).
    * *Why?* Unfiltered `.har` files from e-commerce sites can exceed 300MB, which will crash the server and cause a `ClientDisconnect` error during upload. **Only analytical data matters!**

    #### 1️⃣ Step 1: Prepare a Clean Environment (Incognito Mode)
    * Always open the target website in a **new Incognito Window** (`Ctrl+Shift+N` or `Cmd+Shift+N`).
    * *Why?* This bypasses all cached cookies, forcing the website to re-display the privacy banner and execute all tracking scripts from scratch.
    
    #### 2️⃣ Step 2: Open the Network Tab in DevTools
    * Go to the website's homepage, press **F12** (or right-click and select **Inspect**).
    * Navigate to the **Network** tab at the top.
    
    #### 3️⃣ Step 3: Configure Persistent Recording (Preserve Log)
    * Ensure the circular recording icon in the top-left corner of the DevTools panel is **red**.
    * ⚠️ **CRITICAL ELEMENT:** Absolutely check the **"Preserve log"** checkbox. If left unchecked, the browser will wipe all captured network traffic the moment you navigate away from the homepage!
    
    #### 4️⃣ Step 4: THE CRITICAL STEP – Full Cookie Acceptance
    * Refresh the page (`F5`). Wait for the privacy consent banner (CMP) to pop up.
    * **Click the primary button to accept all marketing and analytical tracking** (e.g., *'Accept All'*, *'Agree'*).
    * *Why?* Without explicit consent, Enterprise tracking systems remain blocked and won't ping the `.har` file!
    
    #### 5️⃣ Step 5: Execute the Full E-commerce Funnel
    * Click on any item to open the **product page**, then add it to the **cart**.
    * **Slowly scroll to the bottom of the page.** Modern lazy-loading frameworks delay enterprise tags until the user reaches the footer.
    
    #### 6️⃣ Step 6: Export the .HAR File
    * **Right-click** anywhere inside the list of recorded network requests in the DevTools panel.
    * Select **"Save all as HAR with content"**.
    """)
    
    st.success("🎯 Done!")
