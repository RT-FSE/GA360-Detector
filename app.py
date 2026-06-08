import streamlit as st
import json
import pandas as pd
import re
import base64
from urllib.parse import urlparse, parse_qs, unquote, quote

st.set_page_config(page_title="Detektyw GA360 & TechStack", page_icon="🕵️‍♂️", layout="wide")

# --- PANEL BOCZNY (SIDEBAR) ---
st.sidebar.title("⚙️ Tryb Pracy Agenta")
st.sidebar.markdown("**Wersja: Masowa Analiza HAR (Bulk Upload)**")
st.sidebar.info("Moduł automatyczny został wyłączony w celu zapewnienia maksymalnej dokładności danych. Wgraj jeden lub wiele plików .har jednocześnie.")

# --- FUNKCJA WSPÓLNA: PANCERNE FILTROWANIE HAR ---
def filtruj_logi_har(har_json):
    filtered_requests = []
    wykryte_inne = set()
    
    # Słownik footprintów innych popularnych systemów analitycznych
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
        
        if any(url_lower.endswith(ext) or f"{ext}?" in url_lower for ext in [".js", ".css", ".woff", ".woff2", ".ttf", ".png", ".jpg", ".svg", ".gif"]):
            continue
        
        is_analytics = False
        if any(x in url_lower for x in ["collect", "google-analytics", "doubleclick", "analytics", "/gtm", "metrics", "stat", "track", "tag", "data", "pagead", "activityi", "fls."]):
            is_analytics = True
            
        query_string = entry.get("request", {}).get("queryString", [])
        for q in query_string:
            if q.get("name") in ["tid", "v", "en"]:
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
# SILNIK LOKALNEJ ANALIZY
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
        
        # Weryfikacja Server-Side Tagging na podstawie autowykrytej domeny
        if czysta_domena != "Nieznana domena" and czysta_domena in hostname and not any(x in hostname for x in ["google", "doubleclick", "analytics", "facebook"]):
            server_side_domain = hostname
            
        if any(x in hostname for x in ["doubleclick.net", "fls.doubleclick.net", "ad.doubleclick.net"]) or any(x in original_url.lower() for x in ["g.doubleclick", "/ddm/activity/", "/activityi", "/pagead/", "dc_pre="]):
            gmp_detected = "Tak"
            
        base_params = {}
        for q in req.get("query_string", []):
            name = q.get("name")
            value = q.get("value", "")
            if name: base_params[name] = value

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
    r8 = "[✅]" if gmp_detected == "Tak" else "[❌]"
    
    twarda_regula_zlamana = (r1 == "[✅]" or r2 == "[✅]" or r3 == "[✅]" or r4 == "[✅]")
    miekkie_poszlaki_licznik = sum([1 for r in [r5, r6, r7, r8] if r == "[✅]"])
    
    puste_zdarzenia_ga4 = (max_ep_per_event == 0 and max_item_params == 0 and len(globalne_ep_params) == 0)
    
    if len(wykryte_ga4_tids) == 0:
        if wykryte_inne:
            if "Adobe Analytics (Enterprise)" in wykryte_inne:
                werdykt = "Adobe Analytics (Enterprise)"
                pewnosc = "100%"
            else:
                werdykt = f"Inny system ({', '.join(wykryte_inne)})"
                pewnosc = "95%"
        else:
            werdykt = "Brak Analityki (Nieznany system)"
            pewnosc = "90%"
    else:
        if twarda_regula_zlamana:
            werdykt = "GA 360"
            pewnosc = "100%"
        elif puste_zdarzenia_ga4 and miekkie_poszlaki_licznik > 0:
            werdykt = "Darmowe GA4 (Puste parametry)"
            pewnosc = "85%"
        elif r5 == "[✅]" or miekkie_poszlaki_licznik >= 2:
            werdykt = "Prawdopodobnie GA 360"
            pewnosc = "75%"
        elif miekkie_poszlaki_licznik == 1:
            werdykt = "Darmowe GA4"
            pewnosc = "80%" 
        else:
            werdykt = "Darmowe GA4"
            pewnosc = "95%"

    tid_ga4_display = ", ".join(list(wykryte_ga4_tids)) if wykryte_ga4_tids else "Brak Google Analytics"
    tid_ads_display = f" (+ Ads/DV360: {', '.join(list(wykryte_ads_tids))})" if wykryte_ads_tids else ""
    full_tid_display = tid_ga4_display + tid_ads_display
    inne_systemy_display = ", ".join(wykryte_inne) if wykryte_inne else "Nie wykryto alternatywnych trackerów"

    markdown_output = f"""
* **WERDYKT:** **{werdykt}**
* **PEWNOŚĆ:** `{pewnosc}`
* **Wykryte Measurement ID (tid):** `{full_tid_display}`
* **Inne systemy analityczne:** `{inne_systemy_display}`

---
### 📋 Kontrola Reguł Analitycznych (Dla ekosystemu Google)

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
        "other_systems": wykryte_inne,
        "reason": f"Przeanalizowano {len(wszystkie_zdarzenia)} zdarzeń Google. Alternatywne systemy: {inne_systemy_display}."
    }
    
    return f"{markdown_output}\n```json\n{json.dumps(json_payload, indent=2)}\n```"

# ==========================================
# INTERFEJS UŻYTKOWNIKA
# ==========================================
st.title("🕵️‍♂️ Detektyw GA360 & TechStack")

tab1, tab2, tab3 = st.tabs(["🚀 Panel Skanowania", "📚 Baza Wiedzy (EDU)", "📥 Instrukcja plików .HAR"])

with tab1:
    excel_data_rows = []

    st.markdown("Wyeksportuj pliki `.har` ze swojej przeglądarki i wgraj je poniżej. **Możesz przeciągnąć wiele plików naraz.**")
    
    # KRYTYCZNA ZMIANA: accept_multiple_files=True pozwala na Bulk Upload
    wgrane_pliki = st.file_uploader("Wybierz pliki .har", type=["har"], accept_multiple_files=True)
    
    if st.button("🔍 Analizuj wgrane pliki"):
        if wgrane_pliki:
            for plik in wgrane_pliki:
                with st.spinner(f"Analiza pliku: {plik.name}..."):
                    try:
                        har_data = json.load(plik)
                        
                        # AUTODETEKCJA DOMENY z nagłówków HAR
                        czysta_domena = plik.name.replace(".har", "") # Fallback
                        try:
                            if "pages" in har_data.get("log", {}) and len(har_data["log"]["pages"]) > 0:
                                pierwsza_strona = har_data["log"]["pages"][0].get("title", "")
                                if pierwsza_strona.startswith("http"):
                                    parsed = urlparse(pierwsza_strona)
                                    czysta_domena = parsed.hostname.replace("www.", "")
                        except Exception:
                            pass

                        filtered_requests, wykryte_inne = filtruj_logi_har(har_data)
                        
                        # Wyświetlanie wyników w rozwijanym akordeonie dla estetyki
                        with st.expander(f"Wynik analizy: {czysta_domena} (Plik: {plik.name})", expanded=False):
                            if not filtered_requests and not wykryte_inne:
                                st.warning("W tym pliku HAR nie znaleziono żadnych skryptów analitycznych. Upewnij się, że plik został poprawnie nagrany.")
                                excel_data_rows.append({
                                    "Domena (z pliku)": czysta_domena,
                                    "Werdykt końcowy": "Błąd / Brak danych",
                                    "Poziom pewności": "0%",
                                    "Identyfikator usługi (TID)": "Brak",
                                    "Alternatywne systemy": "Brak",
                                    "Kluczowe uzasadnienie": "Brak zdarzeń sieciowych."
                                })
                            else:
                                response_text = analizuj_lokalnie(filtered_requests, czysta_domena, wykryte_inne)
                                parts = response_text.split("```json")
                                st.markdown(parts[0])
                                
                                if len(parts) > 1:
                                    extracted_json = json.loads(parts[1].split("```")[0].strip())
                                    excel_data_rows.append({
                                        "Domena (z pliku)": czysta_domena,
                                        "Werdykt końcowy": extracted_json.get("verdict"),
                                        "Poziom pewności": extracted_json.get("confidence"),
                                        "Identyfikator usługi (TID)": extracted_json.get("tid"),
                                        "Alternatywne systemy": ", ".join(extracted_json.get("other_systems", [])),
                                        "Kluczowe uzasadnienie": extracted_json.get("reason")
                                    })
                    except Exception as e:
                        st.error(f"Błąd odczytu pliku {plik.name}: {e}")
        else:
            st.warning("Najpierw wgraj przynajmniej jeden plik .har.")

    # --- TABELA ZBIORCZA ---
    if excel_data_rows:
        st.write("")
        st.subheader("📊 Zbiorcze Zestawienie Wyników (Bulk Export)")
        df = pd.DataFrame(excel_data_rows)
        st.dataframe(df, use_container_width=True)
        
        csv_data = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button(
            label="📥 Pobierz zbiorczy raport CSV",
            data=csv_data,
            file_name="Zbiorczy_Raport_GA360.csv",
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
    st.subheader("🟡 Miękkie Poszlaki Kontekstowe (Analiza Biznesowa)")

    with st.expander("Reguła 5: Łączna suma parametrów eventowych w sesji (>50)"):
        st.markdown("""
        * **Opis:** Łączny limit zarejestrowanych Custom Dimensions dla całej usługi w darmowej wersji wynosi 50, a w GA360 wynosi 125. Jeśli w trakcie jednej sesji system naliczy łącznie ponad 50 unikalnych nazw parametrów `ep.*`, jest to potężna poszlaka wskazująca na budżet klasy Enterprise.
        """)

    with st.expander("Reguła 6: Server-Side Tagging (SST)"):
        st.markdown("""
        * **Opis:** Przesyłanie logów przez niezależny serwer proxy w domenie 1st-party (np. `stat.sklep.pl`) zamiast bezpośrednio do domen Google. Konfiguracja SST wymaga płatnej infrastruktury chmurowej. Ze względu na koszty i złożoność techniczną, SST jest wdrażany prawie wyłącznie przez duże organizacje.
        """)

    with st.expander("Reguła 7: Korporacyjny Multi-tagging (Zbiory Roll-up)"):
        st.markdown("""
        * **Opis:** Wysyłanie identycznych pakietów danych jednocześnie do kilku różnych identyfikatorów pomiarowych (`tid`). Rozwiązanie to jest powszechnie stosowane w grupach kapitałowych i międzynarodowych e-commerce w celu agregacji danych lokalnych do jednej globalnej usługi centralnej.
        """)

    with st.expander("Reguła 8: Ekosystem Google Marketing Platform (GMP)"):
        st.markdown("""
        * **Opis:** Wykrycie w strumieniu sieciowym śladów zaawansowanych systemów reklamowych Google klasy premium (Campaign Manager 360, Display & Video 360, Search Ads 360). Integracje te są natywną domeną płatnego pakietu GA360.
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
