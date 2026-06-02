import streamlit as st
import json
import pandas as pd
import re
import base64
from urllib.parse import urlparse, parse_qs, unquote, quote

st.set_page_config(page_title="GA360 Detector", page_icon="🕵️‍♂️", layout="wide")

# --- PANEL BOCZNY (SIDEBAR) ---
st.sidebar.title("⚙️ Tryb Pracy Agenta")
st.sidebar.markdown("**Wersja: 100% Lokalna analiza plików HAR**")
st.sidebar.info("Używaj wyłącznie wygenerowanych z przeglądarki plików .har.")

# --- FUNKCJA WSPÓLNA: PANCERNE FILTROWANIE HAR ---
def filtruj_logi_har(har_json):
    filtered_requests = []
    for entry in har_json.get("log", {}).get("entries", []):
        original_url = entry.get("request", {}).get("url", "")
        url_lower = original_url.lower()
        
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
        
        # Dekodowanie ukrytych payloadów (Base64)
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
    tid_ads_display = f" (+ Ads/DV360: {', '.join(list(wykryte_ads_tids))})" if wykryte_ads_tids else ""
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
        "reason": f"Przeanalizowano {len(wszystkie_zdarzenia)} zdarzeń z plików HAR. Maksymalna l. custom item-scoped: {max_item_params}."
    }
    
    return f"{markdown_output}\n```json\n{json.dumps(json_payload, indent=2)}\n```"

# ==========================================
# INTERFEJS UŻYTKOWNIKA
# ==========================================
st.title("🕵️‍♂️ Detektyw GA360")

tab1, tab2, tab3 = st.tabs(["🚀 Panel Skanowania", "📚 Baza Wiedzy (EDU)", "📥 Instrukcja plików .HAR"])

with tab1:
    excel_data_rows = []

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

    # --- TABELA ZBIORCZA ---
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
        * **Logika detekcji:** Analizujemy strukturę danych e-commerce. Jeśli pojedynczy produkt (niezależnie czy zapisany w nowym formacie `items.0...` czy legacy `pr1ep...`) zawiera więcej niż 10 niestandardowych cech (po wykluczeniu parametrów natywnych typu brand, price, id), system uruchamia twardy werdykt.
        """)

    st.write("")
    st.subheader("🟡 Miękkie Poszlaki Kontekstowe (Analiza Biznesowa)")

    with st.expander("Reguła 5: Łączna suma parametrów eventowych w sesji (>50)"):
        st.markdown("""
        * **Opis:** Łączny limit zarejestrowanych Custom Dimensions dla całej usługi w darmowej wersji wynosi 50, a w GA360 wynosi 125. Jeśli w trakcie jednej, krótkiej sesji zarejestrowanej w pliku HAR system naliczy łącznie ponad 50 unikalnych nazw parametrów `ep.*`, jest to potężna poszlaka wskazująca na budżet i architekturę klasy Enterprise.
        """)

    with st.expander("Reguła 6: Server-Side Tagging (SST)"):
        st.markdown("""
        * **Opis:** Przesyłanie logów przez niezależny serwer proxy w domenie 1st-party (np. `stat.sklep.pl`) zamiast bezpośrednio do domen Google. Konfiguracja SST wymaga płatnej infrastruktury w Google Cloud Platform (Cloud Run). Ze względu na koszty i złożoność techniczną, SST jest wdrażany prawie wyłącznie przez duże organizacje, które najczęściej posiadają również licencję GA360.
        """)

    with st.expander("Reguła 7: Korporacyjny Multi-tagging (Zbiory Roll-up)"):
        st.markdown("""
        * **Opis:** Wysyłanie identycznych pakietów danych jednocześnie do kilku różnych identyfikatorów pomiarowych (`tid` zaczynających się od `G-` lub `AW-`). Rozwiązanie to jest powszechnie stosowane w grupach kapitałowych i międzynarodowych e-commerce w celu agregacji danych lokalnych do jednej globalnej usługi centralnej.
        """)

    with st.expander("Reguła 8: Ekosystem Google Marketing Platform (GMP)"):
        st.markdown("""
        * **Opis:** Wykrycie w strumieniu sieciowym śladów zaawansowanych systemów reklamowych Google klasy premium (Campaign Manager 360, Display & Video 360, Search Ads 360). Objawia się to obecnością żądań do domen Doubleclick, wywołaniami skryptów Floodlight (`/activityi`), czy identyfikatorami z prefiksem `DC-`. Integracje te są natywną domeną płatnego pakietu GA360.
        """)

with tab3:
    st.title("📥 Instrukcja Generowania Wartościowych Plików .HAR")
    st.markdown("Aby algorytm matematyczny poprawnie przeanalizował strukturę danych i wykrył limity Google Analytics 360, plik logów sieciowych musi zostać wygenerowany zgodnie z poniższą procedurą. **Błędy na tym etapie uniemożliwią poprawną diagnozę.**")
    
    st.info("💡 **Analityczna wskazówka:** Co to jest plik .HAR? To kompletny zapis chronologiczny całej komunikacji sieciowej między Twoją przeglądarką a serwerami zewnętrznymi w trakcie trwania sesji.")
    
    st.markdown("""
    ### 🛠️ Instrukcja Krok po Kroku dla Konsultantów i Handlowców:
    
    #### 1️⃣ Krok 1: Przygotowanie czystego środowiska (Tryb Incognito)
    * Zawsze otwieraj badany serwis w **nowym oknie incognito** przeglądarki (`Ctrl+Shift+N` na Windows lub `Cmd+Shift+N` na Mac).
    * *Dlaczego?* Pozwala to całkowicie ominąć pliki cookie zapisane w pamięci podręcznej (cache). Dzięki temu wymusisz na stronie ponowne wyświetlenie baneru prywatności oraz pełne załadowanie wszystkich skryptów inicjujących od zera.
    
    #### 2️⃣ Krok 2: Uruchomienie zakładki Network w DevTools
    * Wejdź na stronę główną witryny, kliknij klawisz **F12** (lub kliknij prawym przyciskiem myszy w dowolnym miejscu i wybierz **Zbadaj**).
    * Przejdź do górnej zakładki **Network** (Sieć).
    
    #### 3️⃣ Krok 3: Konfiguracja pancernego nagrywania (Preserve Log)
    * Upewnij się, że okrągła ikona nagrywania w lewym górnym rogu DevTools świeci się na **czerwono** (oznacza to, że ruch jest rejestrowany).
    * ⚠️ **NAJWAŻNIEJSZY ELEMENT:** Bezwzględnie zaznacz checkbox **"Preserve log"** (Zachowaj logi). Jeśli tego nie zrobisz, w momencie przejścia ze strony głównej na kartę produktu przeglądarka wyczyści dotychczas zebrany ruch sieciowy i stracisz kluczowe dane startowe!
    
    #### 4️⃣ Krok 4: KROK KRYTYCZNY – Pełna akceptacja Cookies
    * Odśwież stronę (`F5`). Poczekaj na pojawienie się baneru zarządzania prywatnością (CMP).
    * **Kliknij przycisk pełnej akceptacji wszystkich zgód marketingowych i analitycznych** (szukaj fraz: *'Akceptuję wszystko'*, *'Zgadzam się'*, *'Akceptuj wszystkie cookies'*).
    * *Dlaczego to ważne?* Jeśli zamkniesz baner krzyżykiem lub odrzucisz zgody, witryna przejdzie w restrykcyjny tryb **Consent Mode**. W tym trybie tagi reklamowe i zaawansowana analityka e-commerce zostaną całkowicie zablokowane przez przeglądarkę, a nasz detektyw doliczy się 0 zdarzeń!
    
    #### 5️⃣ Krok 5: Przejście pełnej ścieżki e-commerce
    * Nie kończ nagrywania na stronie głównej. Kliknij w dowolny produkt i przejdź na **kartę produktu**.
    * **Przescrolluj kartę produktu powoli do samego dołu.** Wiele nowoczesnych systemów stosuje mechanizm *lazy-loadingu* i odpala bogate skrypty analityczne (w tym customowe parametry produktu) dopiero wtedy, gdy użytkownik fizycznie dotrze ekranem do konkretnych sekcji strony.
    * Opcjonalnie: Dodaj produkt do koszyka lub skorzystaj z wyszukiwarki wewnętrznej. Im więcej zdarzeń wygenerujesz, tym więcej twardych dowodów dostarczysz do analizatora.
    
    #### 6️⃣ Krok 6: Eksport pliku .HAR
    * Po zakończeniu ścieżki kliknij **prawym przyciskiem myszy** w dowolnym miejscu na liście zarejestrowanych żądań sieciowych w panelu DevTools.
    * Wybierz opcję **"Save all as HAR with content"** (Zapisz wszystko jako HAR z zawartością).
    * Zapisz plik na dysku, a następnie wgraj go w polu analizatora w aplikacji.
    """)
    
    st.success("🎯 Gotowe! Tak przygotowany plik HAR gwarantuje 100% precyzji w wykrywaniu systemów klasy enterprise.")
