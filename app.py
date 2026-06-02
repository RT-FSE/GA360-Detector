import streamlit as st
import json
import os
import pandas as pd
import uuid 
import re
from urllib.parse import urlparse, parse_qs, unquote, quote
from playwright.sync_api import sync_playwright

# Wymuszenie instalacji przeglądarki na chmurze Streamlit
os.system("playwright install chromium")

st.set_page_config(page_title="Detektyw GA360", page_icon="🕵️‍♂️", layout="wide")

# --- PANEL BOCZNY (SIDEBAR) ---
st.sidebar.title("⚙️ Tryb Pracy Agenta")
st.sidebar.markdown("**Wersja: 100% Lokalna / Chmurowa**")

tryb_pracy = st.sidebar.radio(
    "Wybierz metodę wprowadzania danych:",
    options=["📥 Wgraj własny plik (.HAR)", "🤖 Automat (Playwright)"],
    help="Użyj uploadu .HAR, jeśli strona blokuje automatyczne boty lub działasz na serwerze chmurowym."
)

st.sidebar.write("---")

if tryb_pracy == "🤖 Automat (Playwright)":
    glebokosc_skanowania = st.sidebar.radio(
        "Głębokość skanowania automatu:",
        options=["Szybka (Strona główna)", "Pełna (Ścieżka e-commerce)"],
        index=1
    )
    tryb_headless = st.sidebar.checkbox(
        "Tryb serwerowy (Headless)", 
        value=True, 
        help="Zaznacz, jeśli aplikacja działa na zewnętrznym serwerze (np. Streamlit Cloud)."
    )
else:
    glebokosc_skanowania = "N/A"
    tryb_headless = True

# --- FUNKCJA WSPÓLNA: PANCERNE FILTROWANIE HAR (Naprawa błędu Chrome DevTools) ---
def filtruj_logi_har(har_json):
    filtered_requests = []
    for entry in har_json.get("log", {}).get("entries", []):
        original_url = entry.get("request", {}).get("url", "")
        url_lower = original_url.lower()
        
        # Odrzucamy typowe śmieci graficzne i skrypty
        if any(url_lower.endswith(ext) or f"{ext}?" in url_lower for ext in [".js", ".css", ".woff", ".woff2", ".ttf", ".png", ".jpg", ".svg", ".gif"]):
            continue
        
        # Poszerzony filtr SGTM
        is_analytics = False
        if any(x in url_lower for x in ["collect", "google-analytics", "doubleclick", "analytics", "/gtm", "metrics", "stat", "track"]):
            is_analytics = True
            
        # Zabezpieczenie: Szukamy TID lub v=2 w parametrach URL nawet jak domena jest nietypowa
        query_string = entry.get("request", {}).get("queryString", [])
        for q in query_string:
            if q.get("name") in ["tid", "v", "en"]:
                is_analytics = True
                break

        if not is_analytics:
            continue
            
        post_data_obj = entry.get("request", {}).get("postData", {})
        post_text = post_data_obj.get("text", "")
        
        # KRYTYCZNA POPRAWKA: Rekonstrukcja ukrytych payloadów z Chrome DevTools
        if not post_text and "params" in post_data_obj:
            reconstructed = []
            for p in post_data_obj["params"]:
                k = p.get("name", "")
                v = p.get("value", "")
                reconstructed.append(f"{quote(k)}={quote(v)}")
            post_text = "&".join(reconstructed)

        filtered_requests.append({
            "url": original_url, 
            "query_string": query_string,
            "post_data": post_text
        })
    return filtered_requests

# ==========================================
# SILNIK LOKALNEJ ANALIZY
# ==========================================
def analizuj_lokalnie(requests_list, czysta_domena):
    max_ep_per_event = 0
    max_custom_param_len = 0
    max_up_per_event = 0
    max_item_params = 0
    globalne_ep_params = set()
    wykryte_ga4_tids = set()
    wykryte_ads_tids = set()
    server_side_domain = "Nie"
    gmp_detected = "Nie"
    
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
        
        if czysta_domena in hostname and not any(x in hostname for x in ["google", "doubleclick", "analytics", "facebook"]):
            server_side_domain = hostname
            
        if any(x in hostname for x in ["doubleclick.net", "fls.doubleclick.net"]) or "g.doubleclick" in original_url.lower() or "/ddm/activity/" in original_url.lower():
            gmp_detected = "Tak"
            
        base_params = {}
        for q in req.get("query_string", []):
            name = q.get("name")
            value = q.get("value", "")
            if name: base_params[name] = value

        post_text = req.get("post_data", "")
        if post_text:
            for line in post_text.split('\r\n'):
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
                    for match in re.findall(r'([a-zA-Z0-9_\.]+)=([^&\s;]+)', line):
                        event_params[match[0]] = match[1]
                    
                wszystkie_zdarzenia.append({"url": original_url, "params": event_params})
        else:
            if base_params:
                wszystkie_zdarzenia.append({"url": original_url, "params": base_params})

    for event in wszystkie_zdarzenia:
        params = event["params"]
        original_url = event["url"]
        
        if "tid" in params and params["tid"]:
            tid_val = str(params["tid"]).upper()
            if tid_val.startswith("G-"):
                wykryte_ga4_tids.add(tid_val)
            elif tid_val.startswith("AW-"):
                wykryte_ads_tids.add(tid_val)
        else:
            tid_match_ga4 = re.search(r'tid=(G-[A-Z0-9]+)', original_url, re.IGNORECASE)
            if tid_match_ga4: 
                wykryte_ga4_tids.add(tid_match_ga4.group(1).upper())
                
            tid_match_aw = re.search(r'tid=(AW-[A-Z0-9\-]+)', original_url, re.IGNORECASE)
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
                
            # Usprawniony Regex dla Custom Metrics (cm) i Custom Dimensions (k)
            match_legacy_item = re.match(r'^(?:pr|pi)(\d+)(?:k|cm|cp\.)([a-zA-Z0-9_]+)', k)
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
    r6 = "[✅]" if server_side_domain != "Nie" else "[❌]"
    r7 = "[✅]" if len(wykryte_ga4_tids) > 1 else "[❌]"
    r8 = "[✅]" if gmp_detected == "Tak" else "[❌]"
    
    twarda_regula_zlamana = (r1 == "[✅]" or r2 == "[✅]" or r3 == "[✅]" or r4 == "[✅]")
    miekkie_poszlaki_licznik = sum([1 for r in [r5, r6, r7, r8] if r == "[✅]"])
    
    if twarda_regula_zlamana:
        werdykt = "GA 360"
        pewnosc = "100%"
    elif r5 == "[✅]" or miekkie_poszlaki_licznik >= 2:
        werdykt = "Prawdopodobnie GA 360"
        pewnosc = "75%"
    elif miekkie_poszlaki_licznik == 1:
        werdykt = "Darmowe GA4"
        pewnosc = "80%" 
    else:
        werdykt = "Darmowe GA4"
        pewnosc = "95%"

    tid_ga4_display = ", ".join(list(wykryte_ga4_tids)) if wykryte_ga4_tids else "Brak GA4"
    tid_ads_display = f" (+ Ads: {', '.join(list(wykryte_ads_tids))})" if wykryte_ads_tids else ""
    full_tid_display = tid_ga4_display + tid_ads_display

    markdown_output = f"""
### 📊 Wynik analizy Google Analytics dla domeny {czysta_domena}
* **WERDYKT:** {werdykt}
* **PEWNOŚĆ:** {pewnosc}
* **Wykryte Measurement ID (tid):** `{full_tid_display}`

---
### 📋 Kontrola Reguł Analitycznych

| Stan | Typ reguły | Reguła walidacyjna / Limit | Wynik analizy sieciowej |
| :---: | :--- | :--- | :--- |
| {r1} | Krytyczna (Twarda) | Liczba parametrów > 25 w evencie | Wykryto maks: {max_ep_per_event} |
| {r2} | Krytyczna (Twarda) | Długość wartości parametru custom > 100 znaków | Najdłuższy niestandardowy: {max_custom_param_len} znaków |
| {r3} | Krytyczna (Twarda) | Właściwości użytkownika (User Properties) > 25 | Wykryto maks: {max_up_per_event} |
| {r4} | Krytyczna (Twarda) | Niestandardowe parametry produktu (item-scoped) > 10 | Wykryto maks: {max_item_params} w jednym produkcie |
| {r5} | Kontekstowa (Miękka) | Suma unikalnych parametrów ep.* w sesji > 50 | Wykryto łącznie: {len(globalne_ep_params)} unikalnych |
| {r6} | Kontekstowa (Miękka) | Server-Side Tagging (Endpoint w 1st-party domain) | Wykryto punkt zbiórki: {server_side_domain} |
| {r7} | Kontekstowa (Miękka) | Korporacyjny Multi-tagging | GA4 tagi: {"Tak ("+str(len(wykryte_ga4_tids))+")" if len(wykryte_ga4_tids)>1 else "Nie"} |
| {r8} | Kontekstowa (Miękka) | Ekosystem Google Marketing Platform | Wykryto tagi Floodlight / DoubleClick: {gmp_detected} |
"""
    json_payload = {
        "verdict": werdykt,
        "confidence": pewnosc,
        "tid": full_tid_display,
        "reason": f"Maks. custom item-scoped: {max_item_params}. Zmienne sesji ep.*: {len(globalne_ep_params)}."
    }
    
    return f"{markdown_output}\n```json\n{json.dumps(json_payload, indent=2)}\n```"

# ==========================================
# INTERFEJS UŻYTKOWNIKA
# ==========================================
st.title("🕵️‍♂️ Detektyw GA360")

tab1, tab2 = st.tabs(["🚀 Panel Skanowania", "📚 Baza Wiedzy (EDU)"])

with tab1:
    excel_data_rows = []

    # --- TRYB 1: UPLOAD HAR ---
    if tryb_pracy == "📥 Wgraj własny plik (.HAR)":
        st.markdown("Wyeksportuj plik `.har` ze swojej przeglądarki (Zakładka Network w DevTools) i wgraj go poniżej.")
        
        domena_docelowa = st.text_input("Główna domena badanego sklepu (np. euro.com.pl):", help="Potrzebne do poprawnego zbadania Server-Side Taggingu.")
        wgrany_plik = st.file_uploader("Wybierz plik .har", type=["har"])
        
        if st.button("🔍 Analizuj wgrany plik"):
            if not domena_docelowa:
                st.error("Proszę wpisać domenę sklepu przed analizą.")
            elif wgrany_plik is not None:
                with st.spinner("Analiza struktury HAR..."):
                    try:
                        har_data = json.load(wgrany_plik)
                        filtered_requests = filtruj_logi_har(har_data)
                        
                        if not filtered_requests:
                            st.warning("Brak skryptów GA4/GMP w tym pliku HAR. Pamiętaj, aby plik był poprawnie nagrany.")
                        else:
                            czysta_domena = domena_docelowa.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
                            response_text = analizuj_lokalnie(filtered_requests, czysta_domena)
                            
                            st.success("Analiza lokalna ukończona!")
                            parts = response_text.split("```json")
                            st.markdown(parts[0])
                            
                            if len(parts) > 1:
                                extracted_json = json.loads(parts[1].split("```")[0].strip())
                                excel_data_rows.append({
                                    "Domena": czysta_domena,
                                    "Werdykt końcowy": extracted_json.get("verdict"),
                                    "Poziom pewności": extracted_json.get("confidence"),
                                    "Identyfikator usługi (TID)": extracted_json.get("tid"),
                                    "Kluczowe uzasadnienie": extracted_json.get("reason")
                                })
                    except Exception as e:
                        st.error(f"Błąd odczytu pliku: {e}")
            else:
                st.warning("Najpierw wgraj plik .har.")

    # --- TRYB 2: AUTOMAT PLAYWRIGHT ---
    elif tryb_pracy == "🤖 Automat (Playwright)":
        st.markdown("Wpisz domeny (jedna pod drugą). Bot pobierze pełne logi sieciowe, a lokalny algorytm Pythona natychmiast sprawdzi 8 reguł.")
        domeny_input = st.text_area("Lista domen do sprawdzenia:", height=150, placeholder="renault.pl\nhttps://euro.com.pl/telefony/jakis-model.bhtml")

        if st.button("🚀 Uruchom Automata"):
            if not domeny_input.strip():
                st.error("Wpisz przynajmniej jedną domenę!")
                st.stop()
                
            domeny = [d.strip() for d in domeny_input.split("\n") if d.strip()]
            
            for domena in domeny:
                oryginalny_url = domena.replace(" ", "")
                url_do_otwarcia = oryginalny_url if oryginalny_url.startswith("http") else f"https://{oryginalny_url}"
                czysta_domena = oryginalny_url.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
                
                unique_id = uuid.uuid4().hex[:8]
                temp_har_path = f"temp_{czysta_domena}_{unique_id}.har"
                
                with st.expander(f"🌐 Zobacz raport dla: {czysta_domena}", expanded=True):
                    try:
                        with st.spinner("Pobieranie ruchu sieciowego (Playwright)..."):
                            try:
                                with sync_playwright() as p:
                                    browser = p.chromium.launch(headless=tryb_headless)
                                    context = browser.new_context(
                                        record_har_path=temp_har_path, 
                                        ignore_https_errors=True,
                                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                                    )
                                    page = context.new_page()
                                    
                                    try:
                                        page.set_default_navigation_timeout(25000) 
                                        page.set_default_timeout(10000)            
                                        page.goto(url_do_otwarcia, wait_until="load")
                                        page.wait_for_timeout(3000)
                                        
                                        try:
                                            cookie_selectors = [
                                                "button:has-text('W porządku')", "button:has-text('Zaakceptuj wszystko')", 
                                                "button:has-text('Akceptuję')", "button:has-text('Allow all')"
                                            ]
                                            full_selector = ", ".join(cookie_selectors)
                                            visible_cookie_btn = page.locator(full_selector).filter(visible=True).first
                                            if visible_cookie_btn.count() > 0:
                                                visible_cookie_btn.click(timeout=4000)
                                                page.wait_for_timeout(2000)
                                        except Exception:
                                            pass
                                        
                                        if "Pełna" in glebokosc_skanowania:
                                            try:
                                                search_input = page.locator("input[type='search'], input[name*='search'], input[placeholder*='szukaj']").filter(visible=True).first
                                                if search_input.count() > 0:
                                                    search_input.fill("test")
                                                    try:
                                                        with page.expect_navigation(timeout=5000):
                                                            search_input.press("Enter")
                                                    except: pass
                                                    page.wait_for_timeout(3000)
                                            except: pass
                                            
                                            try:
                                                item_links = page.locator("a[href*='produkt'], a[href*='product'], a[href*='/p/'], .product a").filter(visible=True)
                                                if item_links.count() > 0:
                                                    try:
                                                        with page.expect_navigation(timeout=5000):
                                                            item_links.first.click()
                                                    except: pass
                                                    page.wait_for_timeout(3000)
                                            except: pass
                                                
                                            try:
                                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                                page.wait_for_timeout(3000)
                                            except: pass
                                        else:
                                            try:
                                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                                page.wait_for_timeout(3000)
                                            except: pass
                                    finally:
                                        context.close()
                                        browser.close()
                            except Exception as p_err:
                                st.error(f"Błąd pobierania danych sieciowych: {p_err}")
                                continue

                        with st.spinner("Analiza strumienia danych..."):
                            if not os.path.exists(temp_har_path):
                                st.error("Brak pliku logów.")
                                continue
                                
                            with open(temp_har_path, "r", encoding="utf-8-sig") as f:
                                har_json = json.load(f)
                            
                            filtered_requests = filtruj_logi_har(har_json)
                            
                            if not filtered_requests:
                                st.warning("Brak śladów GA4/GMP.")
                                continue

                            response_text = analizuj_lokalnie(filtered_requests, czysta_domena)
                            st.success("Analiza ukończona!")
                            
                            parts = response_text.split("```json")
                            st.markdown(parts[0])
                            
                            if len(parts) > 1:
                                extracted_json = json.loads(parts[1].split("```")[0].strip())
                                excel_data_rows.append({
                                    "Domena": czysta_domena,
                                    "Werdykt końcowy": extracted_json.get("verdict"),
                                    "Poziom pewności": extracted_json.get("confidence"),
                                    "Identyfikator usługi (TID)": extracted_json.get("tid"),
                                    "Kluczowe uzasadnienie": extracted_json.get("reason")
                                })
                                
                    except Exception as loop_error:
                        st.error(f"Błąd krytyczny pętli: {loop_error}")
                    finally:
                        if os.path.exists(temp_har_path):
                            os.remove(temp_har_path)

# --- TABELA ZBIORCZA (Wspólna dla obu trybów) ---
    if excel_data_rows:
        st.write("")
        st.subheader("📊 Zbiorcze Zestawienie Wyników")
        df = pd.DataFrame(excel_data_rows)
        st.dataframe(df, use_container_width=True)
        
        csv_data = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button(
            label="📥 Pobierz raport CSV",
            data=csv_data,
            file_name="Raport_GA360.csv",
            mime="text/csv"
        )

with tab2:
    st.title("📚 Baza Wiedzy Analitycznej & Biznesowej")
    st.markdown("Dokumentacja logiczna reguł wbudowana prosto w silnik aplikacji.")
    st.info("Wszystkie limity są twardo zakodowane w funkcjach filtrujących Pythona.")
