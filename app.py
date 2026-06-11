import streamlit as st
import json
import pandas as pd
import re
import base64
from urllib.parse import urlparse, parse_qs, unquote, quote

st.set_page_config(page_title="GA360 Detector", page_icon="🕵️‍♂️", layout="wide")

# --- PANEL BOCZNY (SIDEBAR) ---
st.sidebar.markdown("**Tryb pracy: Masowa Analiza HAR (Bulk Upload)**")
st.sidebar.caption("Wersja: 21")

st.sidebar.info("""
**🔄 Co nowego w wersji 21?**
* **Fix wyświetlania CM360:** Naprawiono błąd renderowania tabeli Markdown – teraz wszystkie cztery sygnatury Ad Servera są w pełni widoczne.
* **Rebalans Scoringu:** Zwiększono wagę kategorii Infrastruktura (do 40 pkt). Wykrycie Campaign Managera 360 daje teraz aż 20 punktów, dwukrotnie więcej niż zwykłe DV360.
* **Nowa nomenklatura reguł:** Uporządkowano nazewnictwo w tabeli wyników według przejrzystego schematu (Typ Główny + Doprecyzowanie).
""")

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
def analizuj_lokalnie(requests_list, czysta_domena, wykryte_inne):
    max_ep_per_event = 0
    max_custom_param_len = 0
    max_up_per_event = 0
    max_item_params = 0
    globalne_ep_params = set()
    wykryte_ga4_tids = set()
    wykryte_ads_tids = set()
    server_side_domain = "Nie"
    
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
        
        if czysta_domena != "Nieznana domena" and czysta_domena in hostname and not any(x in hostname for x in ["google", "doubleclick", "analytics", "facebook"]):
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
    r6 = "[✅]" if server_side_domain != "Nie" else "[❌]"
    r7 = "[✅]" if len(wykryte_ga4_tids) > 1 else "[❌]"
    
    cm360_evidence = cm360_ddm or cm360_cost or cm360_qty or cm360_dclid
    r8 = "[✅]" if cm360_evidence else "[❌]"
    r9 = "[✅]" if gmp_evidence else "[❌]"
    
    cm360_ddm_str = "Tak" if cm360_ddm else "Nie"
    cm360_cost_str = "Tak" if cm360_cost else "Nie"
    cm360_qty_str = "Tak" if cm360_qty else "Nie"
    cm360_dclid_str = "Tak" if cm360_dclid else "Nie"
    
    # Używamy przecinków zamiast pionowej kreski, aby nie popsuć tabeli w Markdownie
    cm360_szczegoly = f"**/ddm/:** {cm360_ddm_str}, **cost:** {cm360_cost_str}, **qty:** {cm360_qty_str}, **dclid:** {cm360_dclid_str}"
    
    twarda_regula_zlamana = (r1 == "[✅]" or r2 == "[✅]" or r3 == "[✅]" or r4 == "[✅]")
    puste_zdarzenia_ga4 = (max_ep_per_event == 0 and max_item_params == 0 and len(globalne_ep_params) == 0)

    # --- MATEMATYKA (DYNAMIC SCORING) ---
    infra_score = 0
    if r6 == "[✅]": infra_score += 10
    if r7 == "[✅]": infra_score += 10
    
    if cm360_evidence:
        infra_score += 20  # Wdrożenie premium CM360 (max punktów)
    elif gmp_evidence:
        infra_score += 10  # Podstawowe wdrożenie DV360
    
    data_score_ep = int(min((max_ep_per_event / 25) * 30, 30))
    data_score_gl = int(min((len(globalne_ep_params) / 50) * 29, 29))
    
    total_score = infra_score + data_score_ep + data_score_gl

    if len(wykryte_ga4_tids) == 0:
        werdykt = "Brak Google Analytics"
        uzasadnienie_tekst = "Brak ruchu Google. Klasyfikacja oparta na sygnaturach rynkowych alternatyw."
        if wykryte_inne:
            if "Adobe Analytics (Enterprise)" in wykryte_inne:
                pewnosc = "100%"
            else:
                pewnosc = "95%"
        else:
            pewnosc = "90%"
    else:
        uzasadnienie_tekst = f"Punkty analizy: {total_score}/99 pkt (Infra: {infra_score}/40 pkt, Dane_Event: {data_score_ep}/30 pkt, Dane_Sesja: {data_score_gl}/29 pkt)"
        
        if twarda_regula_zlamana:
            werdykt = "GA 360"
            pewnosc = "100%"
        elif total_score >= 60:
            werdykt = "Prawdopodobnie GA 360"
            pewnosc = f"{total_score}%"
        elif infra_score >= 20 and total_score < 60:
            werdykt = "Darmowe GA4 (Zaawansowana infrastruktura)"
            pewnosc = f"{100 - total_score}%"
        elif puste_zdarzenia_ga4:
            werdykt = "Darmowe GA4 (Puste parametry)"
            pewnosc = "95%"
        else:
            werdykt = "Darmowe GA4"
            pewnosc = f"{100 - total_score}%"

    tid_ga4_display = ", ".join(list(wykryte_ga4_tids)) if wykryte_ga4_tids else "Brak Google Analytics"
    inny_system_display = f"Tak, {', '.join(wykryte_inne)}" if wykryte_inne else "Nie"

    markdown_output = f"""
* **DOMENA / SERWIS:** `{czysta_domena}`
* **WERDYKT:** **{werdykt}**
* **PEWNOŚĆ WERDYKTU:** `{pewnosc}`
* **INNY SYSTEM ANALITYCZNY:** `{inny_system_display}`
* **Wykryte Measurement ID (tid):** `{tid_ga4_display}`

---
### 📋 Kontrola Reguł Analitycznych (Dla ekosystemu Google)

| Stan | Typ reguły | Reguła walidacyjna / Limit | Wynik analizy sieciowej |
| :---: | :--- | :--- | :--- |
| {r1} | Twarda (Limit zdarzenia) | Liczba parametrów > 25 w evencie | Wykryto maks: {max_ep_per_event} |
| {r2} | Twarda (Limit rozmiaru) | Długość wartości parametru custom > 100 znaków | Najdłuższy niestandardowy: {max_custom_param_len} znaków |
| {r3} | Twarda (Limit użytkownika) | Właściwości użytkownika (User Properties) > 25 | Wykryto maks: {max_up_per_event} |
| {r4} | Twarda (Limit produktu) | Niestandardowe parametry produktu (item-scoped) > 10 | Wykryto maks: {max_item_params} w jednym produkcie |
| {r5} | Kontekstowa (Gęstość danych) | Suma unikalnych parametrów ep.* w sesji > 50 | Wykryto łącznie: {len(globalne_ep_params)} unikalnych |
| {r6} | Kontekstowa (Architektura IT) | Server-Side Tagging (Endpoint w 1st-party domain) | Wykryto punkt zbiórki: {server_side_domain} |
| {r7} | Kontekstowa (Zarządzanie) | Korporacyjny Multi-tagging | GA4 tagi: {"Tak ("+str(len(wykryte_ga4_tids))+")" if len(wykryte_ga4_tids)>1 else "Nie"} |
| {r8} | Kontekstowa (Ad Server) | Ad Server: Campaign Manager 360 | {cm360_szczegoly} |
| {r9} | Kontekstowa (DSP) | DSP: Display & Video 360 | Bazowe tagi Floodlight: {"Tak" if gmp_evidence else "Nie"} |
"""
    json_payload = {
        "verdict": werdykt,
        "confidence": pewnosc,
        "tid": tid_ga4_display,
        "other_systems_text": inny_system_display,
        "reason": uzasadnienie_tekst
    }
    
    json_str = json.dumps(json_payload, indent=2)
    ticks = "`" * 3
    return f"{markdown_output}\n{ticks}json\n{json_str}\n{ticks}"

# ==========================================
# INTERFEJS UŻYTKOWNIKA
# ==========================================
st.title("🕵️‍♂️ GA360 Detector")

tab1, tab2, tab3 = st.tabs(["🚀 Panel Skanowania", "📚 Baza Wiedzy (EDU)", "📥 Instrukcja plików .HAR"])

with tab1:
    excel_data_rows = []

    st.markdown("Wyeksportuj pliki `.har` ze swojej przeglądarki i wgraj je poniżej. **Możesz przeciągnąć wiele plików naraz.**")
    
    wgrane_pliki = st.file_uploader("Wybierz pliki .har", type=["har"], accept_multiple_files=True)
    
    if st.button("🔍 Analizuj wgrane pliki"):
        if wgrane_pliki:
            for plik in wgrane_pliki:
                with st.spinner(f"Analiza pliku: {plik.name}..."):
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
                        
                        with st.expander(f"{czysta_domena} - Analiza wyniku (Plik: {plik.name})", expanded=False):
                            if not filtered_requests and not wykryte_inne:
                                st.warning("W tym pliku HAR nie znaleziono żadnych skryptów analitycznych. Upewnij się, że plik został poprawnie nagrany.")
                                excel_data_rows.append({
                                    "Domena (z pliku)": czysta_domena,
                                    "Werdykt końcowy": "Błąd / Brak danych",
                                    "Pewność werdyktu": "0%",
                                    "Identyfikator usługi (TID)": "Brak",
                                    "Inny system analityczny": "Nie",
                                    "Kluczowe uzasadnienie": "Brak zdarzeń sieciowych."
                                })
                            else:
                                response_text = analizuj_lokalnie(filtered_requests, czysta_domena, wykryte_inne)
                                
                                ticks = "`" * 3
                                parts = response_text.split(f"{ticks}json")
                                st.markdown(parts[0])
                                
                                if len(parts) > 1:
                                    extracted_json = json.loads(parts[1].split(ticks)[0].strip())
                                    excel_data_rows.append({
                                        "Domena (z pliku)": czysta_domena,
                                        "Werdykt końcowy": extracted_json.get("verdict"),
                                        "Pewność werdyktu": extracted_json.get("confidence"),
                                        "Identyfikator usługi (TID)": extracted_json.get("tid"),
                                        "Inny system analityczny": extracted_json.get("other_systems_text"),
                                        "Kluczowe uzasadnienie": extracted_json.get("reason")
                                    })
                    except Exception as e:
                        st.error(f"Błąd odczytu pliku {plik.name}: {e}")
        else:
            st.warning("Najpierw wgraj przynajmniej jeden plik .har.")

    if excel_data_rows:
        st.write("")
        st.subheader("📊 Zbiorcze Zestawienie Wyników (Bulk Export)")
        df = pd.DataFrame(excel_data_rows)
        st.dataframe(df, use_container_width=True)
        
        csv_data = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button(
            label="📥 Pobierz zbiorczy raport CSV",
            data=csv_data,
            file_name="Zbiorczy_Raport_GA360_Detector.csv",
            mime="text/csv"
        )

with tab2:
    st.title("📚 Baza Wiedzy Analitycznej & Biznesowej")
    st.markdown("Dokumentacja logiczna reguł wbudowana bezpośrednio w silnik weryfikacyjny detektywa.")
    
    st.subheader("🔴 Twarde Reguły i Limity (100% Pewności)")
    
    with st.expander("Reguła 1: Liczba parametrów niestandardowych w zdarzeniu (>25)"):
        st.markdown("""
        * **Tło techniczne:** W darmowej wersji Google Analytics 4 obowiązuje restrykcyjny limit **25 niestandardowych parametrów** przypisanych do jednego zdarzenia. Licencja korporacyjna **GA360 podnosi ten limit do 100**.
        * **Logika detekcji:** Skrypt zlicza unikalne parametry z prefiksami `ep.` (tekstowe) oraz `epn.` (numeryczne) wewnątrz pojedynczego pinga sieciowego. Przekroczenie liczby 25 stanowi niezbity dowód na posiadanie usługi premium.
        """)

    with st.expander("Reguła 2: Maksymalna długość wartości parametru (>100 znaków)"):
        st.markdown("""
        * **Tło techniczne:** Standardowe GA4 automatycznie ucina wartości parametrów tekstowych (Custom Dimensions), jeśli przekraczają **100 znaków**. Wersja **GA360 pozwala na przechowywanie ciągów o długości do 500 znaków**. Jest to niezbędne przy zaawansowanym śledzeniu (np. pełne URLe, opisy błędów, zahaszowane identyfikatory).
        * **Logika detekcji:** Silnik mierzy długość odkodowanych ciągów tekstowych parametrów niestandardowych. Zarejestrowanie wartości o długości 101 znaków lub większej automatycznie potwierdza licencję GA360.
        """)

    with st.expander("Reguła 3: Liczba właściwości użytkownika - User Properties (>25)"):
        st.markdown("""
        * **Tło techniczne:** Właściwości użytkownika służą do głębokiej segmentacji (np. poziom lojalności, status subskrypcji). Darmowe GA4 pozwala na rejestrację maksymalnie **25 User Properties na usługę**. Usługa **GA360 zwiększa ten próg do 100**.
        * **Logika detekcji:** Filtrujemy parametry oznaczone prefiksem sieciowym `up.` oraz `upn.`. Przekroczenie liczby 25 unikalnych właściwości w jednym hicie aktywuje twardy werdykt.
        """)

    with st.expander("Reguła 4: Niestandardowe parametry produktu - Item-Scoped (>10)"):
        st.markdown("""
        * **Tło techniczne:** W darmowym GA4 do każdego przedmiotu w tablicy `items` (np. na liście produktów, w koszyku) można dopisać maksymalnie **10 niestandardowych wymiarów**. Wersja **GA360 rozszerza ten limit do 27 parametrów per produkt**.
        * **Logika detekcji:** Analizujemy strukturę danych e-commerce. Jeśli pojedynczy produkt zawiera więcej niż 10 niestandardowych cech (po wykluczeniu parametrów natywnych typu brand, price, id), system uruchabia twardy werdykt.
        """)

    st.write("")
    st.subheader("🟡 Dynamiczny Scoring Kontekstowy (Analiza Gęstości Danych)")

    with st.expander("Jak czytać Pewność vs Punkty? (Instrukcja dekodowania)"):
        st.markdown("""
        System rozróżnia dwa pojęcia: **Pewność Werdyktu (%)** oraz **Punkty analityczne (max 99 pkt)**. 
        Zazwyczaj te liczby są takie same. Rozjazd pojawia się w specyficznych sytuacjach, co pozwala zachować precyzję detekcji. W wyeksportowanym pliku CSV w kolumnie "Kluczowe uzasadnienie" znajdziesz rozbicie punktów na kategorie:

        * **Infra (max 40 pkt):** Oceniana jest droga infrastruktura. System daje po 10 pkt za Server-Side Tagging, 10 pkt za Multi-tagging, oraz aż **20 pkt za wykrycie Campaign Managera 360** (lub 10 pkt za standardowe DV360).
        * **Dane_Event (max 30 pkt):** Ocenia ciężar największego pojedynczego kliknięcia. Im bliżej darmowego limitu 25 parametrów w jednym hicie, tym więcej punktów. Wynik 0 pkt oznacza analitykę "z pudełka" (brak własnych zmiennych). 
        * **Dane_Sesja (max 29 pkt):** Ocenia bogactwo słownika danych dla całej domeny. Dąży do nagradzania przekroczenia bariery 50 unikalnych parametrów w sesji.
        
        **Kiedy Pewność (%) zachowuje się inaczej niż wyliczone Punkty?**
        * **Przypadek 1 (Wysoka pewność darmowego GA4):** Sklep zdobył tylko 22/99 punktów, co oznacza, że szansa na posiadanie płatnego GA360 jest znikoma. Wtedy system dokonuje inwersji i stwierdza: Skoro mam ułamek szans na GA360, to moja pewność, że jest to Darmowe GA4 wynosi aż **78%** (`100 - 22`). 
        * **Przypadek 2 (Twardy Dowód):** Klient zdobył tylko 50 punktów, ale w jednym ze zdarzeń przekroczył sztywny limit GA4 (np. użył 26 parametrów). Twardy dowód natychmiast ignoruje niską punktację z innych kategorii i ustawia Pewność Werdyktu na **100% GA360**.
        """)

    with st.expander("Wykrywanie Ad Servera: Campaign Manager 360 vs DV360"):
        st.markdown("""
        * **Tło techniczne:** Zarówno DV360, jak i CM360 współdzielą te same tagi konwersji (Floodlight). Jednak system potrafi rozpoznać droższy Ad Server (CM360) po charakterystycznych śladach sieciowych.
        * **Ślad 1 (Identyfikator kliknięcia):** Obecność sygnatury `dclid=` (DoubleClick ID) w parametrach to dowód na bezpośrednie wejście z reklamy CM360.
        * **Ślad 2 (Ścieżki DDM):** Obecność ciągów `/ddm/` (Direct Digital Marketing) oraz skryptów `dcmads.js` w URLach zapytań do infrastruktury DoubleClick.
        * **Ślad 3 (Natywne parametry e-commerce):** Tagi sprzedażowe CM360 używają wbudowanych parametrów `cost=` (przychód) oraz `qty=` (ilość). Czyste DV360 zbiera te dane zazwyczaj przez zmienne niestandardowe (np. `u1=`, `u2=`).
        * **Znaczenie biznesowe:** Wykrycie CM360 daje klientowi dwukrotnie więcej punktów w kategorii Infrastruktury. To potężny sygnał, że klient posiada scentralizowane zarządzanie kampaniami, ogromne budżety mediowe i jest gotowy na rozwiązania Enterprise.
        """)

with tab3:
    st.title("📥 Instrukcja Generowania Wartościowych Plików .HAR")
    st.markdown("Aby algorytm matematyczny poprawnie przeanalizował strukturę danych i wykrył systemy analityczne, plik logów sieciowych musi zostać wygenerowany zgodnie z poniższą procedurą.")
    
    st.markdown("""
    ### 🛠️ Instrukcja Krok po Kroku dla Konsultantów i Handlowców:
    
    #### 1️⃣ Krok 1: Przygotowanie czystego środowiska (Tryb Incognito)
    * Zawsze otwieraj badany serwis w **nowym oknie incognito** przeglądarki (`Ctrl+Shift+N` lub `Cmd+Shift+N`).
    * *Dlaczego?* Pozwala to całkowicie ominąć pliki cookie zapisane w pamięci podręcznej. Dzięki temu wymusisz na stronie ponowne wyświetlenie baneru prywatności oraz pełne załadowanie wszystkich skryptów inicjujących od zera.
    
    #### 2️⃣ Krok 2: Uruchomienie zakładki Network w DevTools
    * Wejdź na stronę główną witryny, kliknij klawisz **F12** (lub kliknij prawym przyciskiem myszy i wybierz **Zbadaj**).
    * Przejdź do górnej zakładki **Network** (Sieć).
    
    #### 3️⃣ Krok 3: Konfiguracja pancernego nagrywania (Preserve Log)
    * Upewnij się, że okrągła ikona nagrywania w lewym górnym rogu DevTools świeci się na **czerwono**.
    * ⚠️ **NAJWAŻNIEJSZY ELEMENT:** Bezwzględnie zaznacz checkbox **"Preserve log"** (Zachowaj logi). Jeśli tego nie zrobisz, w momencie przejścia ze strony głównej na podstronę przeglądarka wyczyści dotychczas zebrany ruch sieciowy!
    
    #### 4️⃣ Krok 4: KROK KRYTYCZNY – Pełna akceptacja Cookies
    * Odśwież stronę (`F5`). Poczekaj na pojawienie się baneru zarządzania prywatnością (CMP).
    * **Kliknij przycisk pełnej akceptacji wszystkich zgód marketingowych i analitycznych** (np. *'Akceptuję wszystko'*, *'Zgadzam się'*, *'Akceptuj wszystkie cookies'*).
    * *Dlaczego to ważne?* Bez akceptacji zgód, systemy analityczne Enterprise zostaną całkowicie zablokowane i nie wygenerują ruchu w pliku HAR!
    
    #### 5️⃣ Krok 5: Przejście pełnej ścieżki e-commerce
    * Kliknij w dowolny produkt i przejdź na **kartę produktu**.
    * **Przescrolluj stronę powoli do samego dołu.** Wiele nowoczesnych systemów stosuje mechanizm *lazy-loadingu* i odpala skrypty analityczne dopiero wtedy, gdy użytkownik fizycznie dotrze ekranem do konkretnych sekcji strony.
    
    #### 6️⃣ Krok 6: Eksport pliku .HAR
    * Kliknij **prawym przyciskiem myszy** w dowolnym miejscu na liście zarejestrowanych żądań w panelu DevTools.
    * Wybierz opcję **"Save all as HAR with content"** (Zapisz wszystko jako HAR z zawartością).
    """)
    
    st.success("🎯 Gotowe! Wrzuć wygenerowane pliki HAR do analizatora (pojedynczo lub masowo).")
