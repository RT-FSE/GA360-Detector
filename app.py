import streamlit as st
import json
import pandas as pd
import re
import base64
from urllib.parse import urlparse, parse_qs, unquote, quote

st.set_page_config(page_title="GA360 Detector", page_icon="🕵️‍♂️", layout="wide")

# ==========================================
# SŁOWNIK WIELOJĘZYCZNOŚCI (I18N DICTIONARY)
# ==========================================
LANGUAGES = {
    "PL": {
        "sidebar_mode": "**Tryb pracy: Masowa Analiza HAR (Bulk Upload)**",
        "sidebar_version": "Wersja: 25",
        "sidebar_changelog": """
**🔄 Co nowego w wersji 25?**
* **Optymalizacja UX:** Usunięto podstawową tabelę zbiorczą na rzecz jednej, wszechstronnej tabeli szczegółowej, która zawiera werdykty i wszystkie złamane limity w jednym miejscu.
* **Samoobjaśniający się eksport:** Zostawiono wiersz legendy (opis reguł), dzięki czemu pobrany plik CSV od razu tłumaczy analitykom znaczenie kolumn.
* **Pełna dwujęzyczność (PL/EN):** Cały interfejs, baza wiedzy i tabele eksportowe przełączają się w locie.
""",
        "title": "GA360 Detector",
        "tabs": ["🚀 Panel Skanowania", "📚 Baza Wiedzy (EDU)", "📥 Instrukcja plików .HAR"],
        "upload_desc": "Wyeksportuj pliki `.har` ze swojej przeglądarki i wgraj je poniżej. **Możesz przeciągnąć wiele plików naraz.**",
        "upload_label": "Wybierz pliki .har",
        "btn_analyze": "🔍 Analizuj wgrane pliki",
        "spinner_msg": "Analiza pliku: {}...",
        "expander_title": "{} - Analiza wyniku (Plik: {})",
        "err_no_scripts": "W tym pliku HAR nie znaleziono żadnych skryptów analitycznych. Upewnij się, że plik został poprawnie nagrany.",
        "err_read_file": "Błąd odczytu pliku {}: {}",
        "warn_no_files": "Najpierw wgraj przynajmniej jeden plik .har.",
        "table_detailed_title": "📊 Szczegółowy Raport Analizy (Zestawienie Zbiorcze)",
        "btn_download_csv_detailed": "📥 Pobierz raport CSV",
        "csv_filename_detailed": "Raport_GA360_Detector.csv",
        "csv_err_msg": "Brak zdarzeń sieciowych.",
        "csv_col_domain": "Domena (z pliku)",
        "csv_col_verdict": "Werdykt końcowy",
        "csv_col_confidence": "Pewność werdyktu",
        "csv_col_tid": "Identyfikator usługi (TID)",
        "csv_col_other": "Inny system analityczny",
        "csv_col_reason": "Kluczowe uzasadnienie",
        "md_domain": "DOMENA / SERWIS",
        "md_verdict": "WERDYKT",
        "md_confidence": "PEWNOŚĆ WERDYKTU",
        "md_other": "INNY SYSTEM ANALITYCZNY",
        "md_tids": "Wykryte Measurement ID (tid)",
        "table_header_status": "Stan",
        "table_header_type": "Typ reguły",
        "table_header_rule": "Reguła walidacyjna / Limit",
        "table_header_result": "Wynik analizy sieciowej",
        "rule_t1_type": "Reguła twarda #1 (Limit zdarzenia)",
        "rule_t1_desc": "Liczba parametrów > 25 w evencie",
        "rule_t1_res": "Wykryto maks: {}",
        "rule_t2_type": "Reguła twarda #2 (Limit rozmiaru)",
        "rule_t2_desc": "Długość wartości parametru custom > 100 znaków",
        "rule_t2_res": "Najdłuższy niestandardowy: {} znaków",
        "rule_t3_type": "Reguła twarda #3 (Limit użytkownika)",
        "rule_t3_desc": "Właściwości użytkownika (User Properties) > 25",
        "rule_t3_res": "Wykryto maks: {}",
        "rule_t4_type": "Reguła twarda #4 (Limit produktu)",
        "rule_t4_desc": "Niestandardowe parametry produktu (item-scoped) > 10",
        "rule_t4_res": "Wykryto maks: {} w jednym produkcie",
        "rule_m5_type": "Reguła kontekstowa #1 (Gęstość danych)",
        "rule_m5_desc": "Suma unikalnych parametrów ep.* w sesji > 50",
        "rule_m5_res": "Wykryto łącznie: {} unikalnych",
        "rule_m6_type": "Reguła kontekstowa #2 (Architektura IT)",
        "rule_m6_desc": "Server-Side Tagging (Endpoint w 1st-party domain)",
        "rule_m6_res": "Wykryto punkt zbiórki: {}",
        "rule_m7_type": "Reguła kontekstowa #3 (Zarządzanie)",
        "rule_m7_desc": "Korporacyjny Multi-tagging",
        "rule_m7_res_yes": "Tak ({})",
        "rule_m7_res_no": "Nie",
        "rule_m8_type": "Reguła kontekstowa #4 (Ad Server)",
        "rule_m8_desc": "Ad Server: Campaign Manager 360",
        "rule_m9_type": "Reguła kontekstowa #5 (DSP)",
        "rule_m9_desc": "DSP: Display & Video 360",
        "rule_m9_res_yes": "Tak",
        "rule_m9_res_no": "Nie",
        "verdict_no_ga": "Brak Google Analytics",
        "verdict_ga360": "GA 360",
        "verdict_prob_ga360": "Prawdopodobnie GA 360",
        "verdict_free_infra": "Darmowe GA4 (Zaawansowana infrastruktura)",
        "verdict_free_empty": "Darmowe GA4 (Puste parametry)",
        "verdict_free": "Darmowe GA4",
        "reason_no_ga": "Brak ruchu Google. Klasyfikacja oparta na sygnaturach rynkowych alternatyw.",
        "reason_pts": "Punkty analizy: {}/99 pkt (Infra: {}/40 pkt, Dane_Event: {}/30 pkt, Dane_Sesja: {}/29 pkt)",
        "edu_title": "📚 Baza Wiedzy Analitycznej & Biznesowej",
        "edu_subtitle": "Dokumentacja logiczna reguł wbudowana bezpośrednio w silnik weryfikacyjny detektywa.",
        "edu_hard_header": "🔴 Twarde Reguły i Limity (100% Pewności)",
        "edu_soft_header": "🟡 Dynamiczny Scoring Kontekstowy (Analiza Gęstości Danych)",
        "har_title": "📥 Instrukcja Generowania Wartościowych Plików .HAR",
        "har_subtitle": "Aby algorytm matematyczny poprawnie przeanalizował strukturę danych i wykrył systemy analityczne, plik logów sieciowych musi zostać wygenerowany zgodnie z poniższą procedurą."
    },
    "EN": {
        "sidebar_mode": "**Operation Mode: Bulk HAR Analysis (Upload)**",
        "sidebar_version": "Version: 25",
        "sidebar_changelog": """
**🔄 What's new in version 25?**
* **UX Optimization:** Removed the basic summary table in favor of a single, comprehensive detailed table that includes both the verdict and all checked rules.
* **Self-Explanatory Export:** Kept the dedicated rule description row, making the downloaded CSV file an instant standalone report.
* **Full Bilingual Support (PL/EN):** The entire UI, knowledge base, and export tables switch instantly.
""",
        "title": "GA360 Detector",
        "tabs": ["🚀 Scan Panel", "📚 Knowledge Base (EDU)", "📥 .HAR File Guide"],
        "upload_desc": "Export `.har` files from your browser and upload them below. **You can drag and drop multiple files at once.**",
        "upload_label": "Choose .har files",
        "btn_analyze": "🔍 Analyze Uploaded Files",
        "spinner_msg": "Analyzing file: {}...",
        "expander_title": "{} - Analysis Result (File: {})",
        "err_no_scripts": "No analytics scripts or footprints were found in this HAR file. Ensure the file was recorded correctly.",
        "err_read_file": "Error reading file {}: {}",
        "warn_no_files": "Please upload at least one .har file first.",
        "table_detailed_title": "📊 Detailed Analysis Report (Bulk Export)",
        "btn_download_csv_detailed": "📥 Download CSV Report",
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
        "rule_m8_desc": "Ad Server: Campaign Manager 360",
        "rule_m9_type": "Contextual rule #5 (DSP)",
        "rule_m9_desc": "DSP: Display & Video 360",
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
        "edu_title": "📚 Analytics & Business Knowledge Base",
        "edu_subtitle": "Logical documentation of the rules embedded directly within the detective's verification engine.",
        "edu_hard_header": "🔴 Hard Rules and Prohibitive Limits (100% Confidence)",
        "edu_soft_header": "🟡 Dynamic Contextual Scoring (Data Density Analysis)",
        "har_title": "📥 Guide to Generating Actionable .HAR Files",
        "har_subtitle": "In order for the mathematical algorithm to properly analyze the data structure and detect enterprise systems, the network logs must be generated according to the following procedure."
    }
}

# --- SELEKCJA JĘZYKA W SIDEBARZE ---
selected_lang = st.sidebar.selectbox("🌐 Język / Language", ["PL", "EN"])
t = LANGUAGES[selected_lang]

st.sidebar.write("")
st.sidebar.markdown(t["sidebar_mode"])
st.sidebar.caption(t["sidebar_version"])
st.sidebar.info(t["sidebar_changelog"])

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
    server_side_domain = "Nie" if selected_lang == "PL" else "No"
    
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
    wszystkie_zdarzenia = []

    for req in requests_list:
        original_url = req.get("url", "")
        parsed_url = urlparse(original_url)
        hostname = parsed_url.hostname or ""
        url_lower = original_url.lower()
        
        domena_check = "Nieznana domena" if selected_lang == "PL" else "Unknown domain"
        if czysta_domena != domena_check and czysta_domena in hostname and not any(x in hostname for x in ["google", "doubleclick", "analytics", "facebook"]):
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
                
            match_legacy_item = re.match(r'^(?:pr|pi)(\d+)(?:k|cm|cd|cg|cp\.|ep\.)([a-zA-Z0-9_\-\s]+)', k)
            if match_legacy_item:
                product_idx = match_legacy_item.group(1)
                custom_idx = match_legacy_item.group(2)
                if product_idx not in custom_item_params_per_product:
                    custom_item_params_per_product[product_idx] = set()
                custom_item_params_per_product[product_idx].add(custom_idx)
            else:
                match_ga4_mp_item = re.match(r'^items\.(\d+)\.(?!item_id|item_name|item_brand|item_category|price|quantity|item_variant|promotion_name|promotion_id|coupon|discount|index|affiliation)(.+)', k)
                if match_ga4_mp_item:
                    product_idx = match_ga4_mp_item.group(1)
                    param_key = match_ga4_mp_item.group(2)
                    if product_idx not in custom_item_params_per_product:
                        custom_item_params_per_product[product_idx] = set()
                    custom_item_params_per_product[product_idx].add(param_key)

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
    r6 = "[✅]" if server_side_domain not in ["Nie", "No"] else "[❌]"
    r7 = "[✅]" if len(wykryte_ga4_tids) > 1 else "[❌]"
    
    cm360_evidence = cm360_ddm or cm360_cost or cm360_qty or cm360_dclid
    r8 = "[✅]" if cm360_evidence else "[❌]"
    r9 = "[✅]" if gmp_evidence else "[❌]"
    
    txt_yes = "Yes" if selected_lang == "EN" else "Tak"
    txt_no = "No" if selected_lang == "EN" else "Nie"
    
    cm360_ddm_str = txt_yes if cm360_ddm else txt_no
    cm360_cost_str = txt_yes if cm360_cost else txt_no
    cm360_qty_str = txt_yes if cm360_qty else txt_no
    cm360_dclid_str = txt_yes if cm360_dclid else txt_no
    
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
    inny_system_display = f"{txt_yes}, {', '.join(wykryte_inne)}" if wykryte_inne else txt_no

    markdown_output = f"""
* **{t_dict['md_domain']}:** `{czysta_domena}`
* **{t_dict['md_verdict']}:** **{werdykt}**
* **{t_dict['md_confidence']}:** `{pewnosc}`
* **{t_dict['md_other']}:** `{inny_system_display}`
* **{t_dict['md_tids']}:** `{tid_ga4_display}`

---
### 📋 {t_dict['edu_subtitle'] if selected_lang=='PL' else 'Rule Validation Summary'}

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
            "r1": f"{r1} {t_dict['rule_t1_res'].format(max_ep_per_event)}",
            "r2": f"{r2} {t_dict['rule_t2_res'].format(max_custom_param_len)}",
            "r3": f"{r3} {t_dict['rule_t3_res'].format(max_up_per_event)}",
            "r4": f"{r4} {t_dict['rule_t4_res'].format(max_item_params)}",
            "r5": f"{r5} {t_dict['rule_m5_res'].format(len(globalne_ep_params))}",
            "r6": f"{r6} {t_dict['rule_m6_res'].format(server_side_domain)}",
            "r7": f"{r7} " + (t_dict['rule_m7_res_yes'].format(len(wykryte_ga4_tids)) if len(wykryte_ga4_tids)>1 else t_dict['rule_m7_res_no']),
            "r8": f"{r8} {cm360_szczegoly_clean}",
            "r9": f"{r9} " + (t_dict['rule_m9_res_yes'] if gmp_evidence else t_dict['rule_m9_res_no'])
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

    st.markdown(t["upload_desc"])
    wgrane_pliki = st.file_uploader(t["upload_label"], type=["har"], accept_multiple_files=True)
    
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
                                    t["csv_col_verdict"]: "Error" if selected_lang=="EN" else "Błąd / Brak danych",
                                    t["csv_col_confidence"]: "0%",
                                    t["csv_col_other"]: "No" if selected_lang=="EN" else "Nie",
                                    t["csv_col_tid"]: "None" if selected_lang=="EN" else "Brak",
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
                                    extracted_json = json.loads(parts[1].split(ticks)[0].strip())
                                    
                                    detailed_row = {
                                        t["csv_col_domain"]: czysta_domena,
                                        t["csv_col_verdict"]: extracted_json.get("verdict"),
                                        t["csv_col_confidence"]: extracted_json.get("confidence"),
                                        t["csv_col_other"]: extracted_json.get("other_systems_text"),
                                        t["csv_col_tid"]: extracted_json.get("tid"),
                                        t["csv_col_reason"]: extracted_json.get("reason")
                                    }
                                    
                                    rules_obj = extracted_json.get("rules", {})
                                    detailed_row[t["rule_t1_type"]] = rules_obj.get("r1", "")
                                    detailed_row[t["rule_t2_type"]] = rules_obj.get("r2", "")
                                    detailed_row[t["rule_t3_type"]] = rules_obj.get("r3", "")
                                    detailed_row[t["rule_t4_type"]] = rules_obj.get("r4", "")
                                    detailed_row[t["rule_m5_type"]] = rules_obj.get("r5", "")
                                    detailed_row[t["rule_m6_type"]] = rules_obj.get("r6", "")
                                    detailed_row[t["rule_m7_type"]] = rules_obj.get("r7", "")
                                    detailed_row[t["rule_m8_type"]] = rules_obj.get("r8", "")
                                    detailed_row[t["rule_m9_type"]] = rules_obj.get("r9", "")
                                    
                                    detailed_data_rows.append(detailed_row)
                    except Exception as e:
                        st.error(t["err_read_file"].format(plik.name, e))
        else:
            st.warning(t["warn_no_files"])

    if detailed_data_rows:
        st.write("---")
        st.subheader(t["table_detailed_title"])
        
        # Wiersz z objaśnieniami dla tabeli
        desc_row = {
            t["csv_col_domain"]: "ℹ️ OPIS REGUŁY" if selected_lang == "PL" else "ℹ️ RULE DESCRIPTION",
            t["csv_col_verdict"]: "-",
            t["csv_col_confidence"]: "-",
            t["csv_col_other"]: "-",
            t["csv_col_tid"]: "-",
            t["csv_col_reason"]: "-",
            t["rule_t1_type"]: t["rule_t1_desc"],
            t["rule_t2_type"]: t["rule_t2_desc"],
            t["rule_t3_type"]: t["rule_t3_desc"],
            t["rule_t4_type"]: t["rule_t4_desc"],
            t["rule_m5_type"]: t["rule_m5_desc"],
            t["rule_m6_type"]: t["rule_m6_desc"],
            t["rule_m7_type"]: t["rule_m7_desc"],
            t["rule_m8_type"]: t["rule_m8_desc"],
            t["rule_m9_type"]: t["rule_m9_desc"]
        }
        
        # Łączymy wiersz z opisami z właściwymi wynikami
        df_detailed = pd.DataFrame([desc_row] + detailed_data_rows)
        st.dataframe(df_detailed, use_container_width=True)
        
        csv_detailed = df_detailed.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button(
            label=t["btn_download_csv_detailed"],
            data=csv_detailed,
            file_name=t["csv_filename_detailed"],
            mime="text/csv"
        )

with tab2:
    if selected_lang == "PL":
        st.title("📚 Baza Wiedzy Analitycznej & Biznesowej")
        st.markdown("Dokumentacja logiczna reguł wbudowana bezpośrednio w silnik weryfikacyjny detektywa.")
        
        st.subheader("🔴 Twarde Reguły i Limity (100% Pewności)")
        with st.expander("Reguła twarda #1: Liczba parametrów niestandardowych w zdarzeniu (>25)"):
            st.markdown("* **Tło techniczne:** W darmowej wersji GA4 obowiązuje restrykcyjny limit **25 niestandardowych parametrów** na event. Licencja **GA360 podnosi go do 100**.\n* **Logika detekcji:** Skrypt zlicza unikalne parametry z prefiksami `ep.` i `epn.`. Przekroczenie 25 to niezbity dowód na usługę premium.")
        with st.expander("Reguła twarda #2: Maksymalna długość wartości parametru (>100 znaków)"):
            st.markdown("* **Tło techniczne:** Standardowe GA4 ucina wartości Custom Dimensions, jeśli przekraczają **100 znaków**. Wersja **GA360 pozwala na ciągi do 500 znaków**.\n* **Logika detekcji:** Silnik mierzy długość parametrów niestandardowych. Zarejestrowanie wartości >100 znaków automatycznie potwierdza licencję GA360.")
        with st.expander("Reguła twarda #3: Liczba właściwości użytkownika - User Properties (>25)"):
            st.markdown("* **Tło techniczne:** Darmowe GA4 pozwala na rejestrację maksymalnie **25 User Properties**. Usługa **GA360 zwiększa ten próg do 100**.\n* **Logika detekcji:** Filtrujemy parametry `up.` oraz `upn.`. Przekroczenie 25 właściwości aktywuje twardy werdykt.")
        with st.expander("Reguła twarda #4: Niestandardowe parametry produktu - Item-Scoped (>10)"):
            st.markdown("* **Tło techniczne:** W darmowym GA4 do każdego przedmiotu w tablicy `items` można dopisać maksymalnie **10 niestandardowych wymiarów**. Wersja **GA360 rozszerza ten limit do 27**.\n* **Logika detekcji:** Jeśli pojedynczy produkt zawiera więcej niż 10 niestandardowych cech, system uruchabia twardy werdykt.")
        
        st.write("")
        st.subheader("🟡 Dynamiczny Scoring Kontekstowy (Analiza Gęstości Danych)")
        with st.expander("Jak czytać Pewność vs Punkty? (Instrukcja dekodowania)"):
            st.markdown("System rozróżnia **Pewność Werdyktu (%)** oraz **Punkty analityczne (max 99 pkt)**. Rozbicie punktów na kategorie:\n\n* **Infra (max 40 pkt):** Ocena infrastruktury. System daje po 10 pkt za Server-Side Tagging i Multi-tagging oraz aż **20 pkt za wykrycie Campaign Managera 360** (lub 10 pkt za DV360).\n* **Dane_Event (max 30 pkt):** Ciężar największego hitu sieciowego.\n* **Dane_Sesja (max 29 pkt):** Bogactwo unikalnych parametrów w sesji (barierą nagrody jest 50 unikalnych parametrów).")
        with st.expander("Wykrywanie Ad Servera: Campaign Manager 360 vs DV360"):
            st.markdown("* **Ślad 1 (Identyfikator kliknięcia):** Sygnatura `dclid=` to dowód na wejście z reklamy CM360.\n* **Ślad 2 (Ścieżki DDM):** Obecność ciągów `/ddm/` oraz skryptów `dcmads.js` w logach sieciowych DoubleClick.\n* **Ślad 3 (Natywne parametry e-commerce):** Tagi sprzedażowe CM360 używają wbudowanych parametrów `cost=` i `qty=`. Czyste DV360 zbiera te dane przez zmienne typu `u1=`.\n* **Znaczenie biznesowe:** Wykrycie CM360 daje podwójne punkty infrastruktury. Świadczy o ogromnych budżetach mediowych i gotowości na rozwiązania Enterprise.")
    else:
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
            st.markdown("* **Technical Background:** In free GA4, you can append a maximum of **10 custom dimensions** to each item in the `items` array. **GA360 expands this limit to 27**.\n* **Detection Logic:** If a single product contains more than 10 custom item-scoped attributes, the system triggers a hard GA360 verdict.")
        
        st.write("")
        st.subheader("🟡 Dynamic Contextual Scoring (Data Density Analysis)")
        with st.expander("How to read Confidence vs Score Points? (Decoding Manual)"):
            st.markdown("The system distinguishes between **Verdict Confidence (%)** and **Analysis Points (max 99 pts)**. Breakdown:\n\n* **Infra (max 40 pts):** Infrastructure evaluation. Awards 10 pts for Server-Side Tagging, 10 pts for Multi-tagging, and **20 pts for Campaign Manager 360** detection (or 10 pts for standard DV360).\n* **Data_Event (max 30 pts):** Evaluates the weight of the single heaviest network hit.\n* **Data_Session (max 29 pts):** Total vocabulary size (rewards properties exceeding 50 unique session parameters).")
        with st.expander("Ad Server Detection: Campaign Manager 360 vs DV360"):
            st.markdown("* **Footprint 1 (Click Identifier):** The presence of a `dclid=` parameter is proof of an entry via a CM360 ad.\n* **Footprint 2 (DDM Paths):** `/ddm/` paths and `dcmads.js` scripts inside DoubleClick network requests.\n* **Footprint 3 (Native E-commerce parameters):** CM360 sales tags utilize built-in `cost=` and `qty=` parameters. Standard DV360 usually collects this via custom variables like `u1=`.\n* **Business Impact:** Detecting CM360 awards double infrastructure points. It signals huge media budgets and enterprise readiness.")

with tab3:
    st.title(t["har_title"])
    st.markdown(t["har_subtitle"])
    
    if selected_lang == "PL":
        st.markdown("""
        ### 🛠️ Instrukcja Krok po Kroku dla Konsultantów i Handlowców:
        
        #### 1️⃣ Krok 1: Przygotowanie czystego środowiska (Tryb Incognito)
        * Zawsze otwieraj badany serwis w **nowym oknie incognito** przeglądarki (`Ctrl+Shift+N` lub `Cmd+Shift+N`).
        * *Dlaczego?* Pozwala to ominąć pliki cookie zapisane w pamięci. Dzięki temu wymusisz ponowne wyświetlenie baneru prywatności oraz pełne załadowanie wszystkich skryptów startowych od zera.
        
        #### 2️⃣ Krok 2: Uruchomienie zakładki Network w DevTools
        * Wejdź na stronę główną, kliknij klawisz **F12** (lub kliknij prawym przyciskiem myszy i wybierz **Zbadaj**).
        * Przejdź do górnej zakładki **Network** (Sieć).
        
        #### 3️⃣ Krok 3: Konfiguracja pancernego nagrywania (Preserve Log)
        * Upewnij się, że okrągła ikona nagrywania w lewym górnym rogu panelu świeci się na **czerwono**.
        * ⚠️ **NAJWAŻNIEJSZY ELEMENT:** Bezwzględnie zaznacz checkbox **"Preserve log"** (Zachowaj logi). Jeśli tego nie zrobisz, w momencie przejścia na podstronę przeglądarka wyczyści dotychczas zebrany ruch sieciowy!
        
        #### 4️⃣ Krok 4: KROK KRYTYCZNY – Pełna akceptacja Cookies
        * Odśwież stronę (`F5`). Poczekaj na baner prywatności (CMP).
        * **Kliknij przycisk pełnej akceptacji wszystkich zgód marketingowych i analitycznych** (np. *'Akceptuję wszystko'*, *'Zgadzam się'*).
        * *Dlaczego to ważne?* Bez akceptacji zgód, systemy klasy Enterprise zostaną zablokowane i nie wygenerują żadnego ruchu sieciowego w pliku HAR!
        
        #### 5️⃣ Krok 5: Przejście pełnej ścieżki e-commerce
        * Kliknij w produkt i przejdź na **kartę produktu**, a następnie dodaj go do **koszyka**.
        * **Przescrolluj stronę powoli do samego dołu.** Mechanizmy *lazy-loadingu* często odpalają skrypty dopiero wtedy, gdy użytkownik fizycznie dotrze ekranem do sekcji koszyka czy stopek.
        
        #### 6️⃣ Krok 6: Eksport pliku .HAR
        * Kliknij **prawym przyciskiem myszy** w dowolnym miejscu na liście żądań w panelu DevTools.
        * Wybierz opcję **"Save all as HAR with content"** (Zapisz wszystko jako HAR z zawartością).
        """)
    else:
        st.markdown("""
        ### 🛠️ Step-by-Step Instructions for Consultants and Sales Teams:
        
        #### 1️⃣ Step 1: Prepare a Clean Environment (Incognito Mode)
        * Always open the target website in a **new Incognito Window** (`Ctrl+Shift+N` or `Cmd+Shift+N`).
        * *Why?* This bypasses all cached cookies. It forces the website to re-display the privacy banner and execute all tracking initialization scripts from scratch.
        
        #### 2️⃣ Step 2: Open the Network Tab in DevTools
        * Go to the website's homepage, press **F12** (or right-click and select **Inspect**).
        * Navigate to the **Network** tab at the top.
        
        #### 3️⃣ Step 3: Configure Persistent Recording (Preserve Log)
        * Ensure the circular recording icon in the top-left corner of the DevTools panel is **red**.
        * ⚠️ **CRITICAL ELEMENT:** Absolutely check the **"Preserve log"** checkbox. If left unchecked, the browser will wipe all captured network traffic the moment you navigate away from the homepage!
        
        #### 4️⃣ Step 4: THE CRITICAL STEP – Full Cookie Acceptance
        * Refresh the page (`F5`). Wait for the privacy consent banner (CMP) to pop up.
        * **Click the primary button to accept all marketing and analytical tracking** (e.g., *'Accept All'*, *'Agree'*).
        * *Why does this matter?* Without explicit consent, Enterprise-level tracking systems will remain entirely blocked and won't fire any network pings into the HAR file!
        
        #### 5️⃣ Step 5: Execute the Full E-commerce Funnel
        * Click on any item to open the **product page**, then add it to the **cart**.
        * **Slowly scroll to the bottom of the page.** Modern lazy-loading and conditional firing frameworks often delay enterprise tags until the user reaches the footer or cart interaction sections.
        
        #### 6️⃣ Step 6: Export the .HAR File
        * **Right-click** anywhere inside the list of recorded network requests in the DevTools panel.
        * Select **"Save all as HAR with content"**.
        """)
        
    st.success("🎯 Done!" if selected_lang=="EN" else "🎯 Gotowe! Wrzuć wygenerowane pliki HAR do analizatora (pojedynczo lub masowo).")
