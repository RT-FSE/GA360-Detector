import streamlit as st
import google.generativeai as genai
import json

# Konfiguracja głównej strony aplikacji
st.set_page_config(page_title="Detektyw GA360", page_icon="🕵️‍♂️", layout="centered")

# --- BRAMKA BEZPIECZEŃSTWA ---
# Zmień to hasło na własne, które podasz zespołowi
HASLO_DOSTEPOWE = "CheckGA4me!" 

wpisane_haslo = st.text_input("Wpisz hasło dostępowe zespołu:", type="password")

if wpisane_haslo != HASLO_DOSTEPOWE:
    st.warning("🔒 Podaj prawidłowe hasło, aby uzyskać dostęp do narzędzia.")
    st.stop() # Blokuje wykonanie reszty kodu, jeśli hasło jest błędne

# --- KONFIGURACJA API GEMINI ---
try:
    # Pobieranie klucza z zakładek "Secrets" w Streamlit Cloud
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # Używamy najnowszego modelu 3.5 Flash
    model = genai.GenerativeModel('gemini-3.5-flash')
except KeyError:
    st.error("❌ Błąd: Brak klucza API. Skonfiguruj 'GEMINI_API_KEY' w zakładce Secrets na Streamlit Cloud.")
    st.stop()

# --- PODZIAŁ NA ZAKŁADKI (NAWIGACJA) ---
tab1, tab2 = st.tabs(["🕵️‍♂️ Detektyw GA360", "📚 Sekcja Edukacyjna (EDU)"])

# ==========================================
# ZAKŁADKA 1: NARZĘDZIE ANALITYCZNE
# ==========================================
with tab1:
    st.title("🕵️‍♂️ Detektyw Google Analytics 360")
    st.markdown("Wgraj plik **.har** (HTTP Archive) wyeksportowany z zakładki Network w przeglądarce. Agent przeanalizuje logi pod kątem limitów wskazujących na licencję Enterprise.")

    uploaded_file = st.file_uploader("Przeciągnij lub wybierz plik .har", type=['har'])

    if uploaded_file is not None:
        with st.spinner('Agent "czyta" logi sieciowe... To zajmie od kilku do kilkunastu sekund (zależnie od wagi pliku).'):
            try:
                # Dekodowanie i parsowanie pliku HAR
                raw_har = uploaded_file.getvalue().decode("utf-8")
                har_json = json.loads(raw_har)
                
                # Ekstrakcja zapytań analitycznych oraz marketingowych Enterprise (DoubleClick/Floodlight)
                filtered_requests = []
                for entry in har_json.get("log", {}).get("entries", []):
                    url = entry.get("request", {}).get("url", "")
                    
                    # Łapiemy GA4 ORAZ systemy DoubleClick/Floodlight/GMP
                    if "collect" in url or "google-analytics" in url or "doubleclick" in url:
                        filtered_requests.append({
                            "url": url,
                            "query_string": entry["request"].get("queryString", []),
                            "post_data": entry["request"].get("postData", {}).get("text", "")
                        })
                    
                    # TWARDA BLOKADA: Pobieramy tylko pierwsze 25 żądań (ochrona przed 429)
                    if len(filtered_requests) >= 25:
                        break
                
                # Zrzucenie odchudzonych danych do stringa, aby podać je modelowi
                har_content = json.dumps(filtered_requests, indent=2)
                
                if not filtered_requests:
                    st.warning("⚠️ Nie znaleziono żadnych żądań do Google Analytics ani Google Marketing Platform w tym pliku.")
                    st.stop()

                # --- PROMPT SYSTEMOWY DLA AGENTA ---
                system_prompt = """
                Jesteś technicznym ekspertem web analityki. Otrzymujesz wyciąg żądań JSON (żądania HTTP do Google Analytics i DoubleClick). 
                Twoim zadaniem jest analiza żądań i ocena, czy strona korzysta z płatnej wersji GA360.

                Zastosuj rygorystyczne reguły decyzyjne i przypisz im odpowiednie ikony (✅ jeśli reguła/poszlaka została spełniona, ❌ jeśli nie):
                1. TWARDA REGUŁA 1: Liczba parametrów 'ep.' oraz 'epn.' w jednym zdarzeniu > 25.
                2. TWARDA REGUŁA 2: Długość wartości parametrów NIESTANDARDOWYCH (custom, zazwyczaj przedrostki ep.* lub klucze własne) > 100 znaków. BEZWZGLĘDNIE WYKLUCZ z tej reguły natywne parametry: 'page_location', 'page_title' oraz 'page_referrer', ponieważ mają one oficjalne wyższe limity w wersji darmowej (odpowiednio 1000, 300 i 420 znaków).
                3. TWARDA REGUŁA 3: Liczba właściwości użytkownika 'up.' lub 'upn.' w sesji > 25.
                4. TWARDA REGUŁA 4: Zlicz unikalne, niestandardowe parametry zdefiniowane na poziomie pojedynczego produktu (item-scoped, wewnątrz obiektów pr1, pr2 itp.). Jeśli dla jednego produktu jest ich > 10 -> WERDYKT GA360 (100%).
                5. MIĘKKA POSZLAKA 1: Suma UNIKALNYCH nazw parametrów 'ep.' ze wszystkich żądań łącznie > 50. (Uwaga metodologiczna: to poszlaka, nie twardy dowód, ponieważ limity 50/125 dotyczą rejestracji wymiarów w panelu admina, a nie samej wysyłki sieciowej).
                6. MIĘKKA POSZLAKA 2: Server-Side Tagging (SSGTM). Sprawdź adres URL żądań. Jeśli żądania idą na domenę/subdomenę inną niż oficjalne serwery Google (nie analytics.google.com, nie google-analytics.com, nie doubleclick.net), oznacza to serwer pośredniczący.
                7. MIĘKKA POSZLAKA 3: Wykrycie wielu identyfikatorów 'tid' (Multi-tagging do kilku G-...).
                8. MIĘKKA POSZLAKA 4: Ślady integracji z Google Marketing Platform. Szukaj żądań zawierających w URL frazę 'doubleclick' oraz specyficznych znaczników dla tagów Floodlight (np. aktywności typu 'activity', parametry 'src=', 'type=', 'cat=' służące do raportowania konwersji w Campaign Manager 360 / DV360).

                Zwróć odpowiedź w czystym Markdown, dokładnie w formacie:
                ### 📊 Wynik analizy Google Analytics
                * **WERDYKT:** [GA 360 / Darmowe GA4 / Prawdopodobnie GA 360]
                * **PEWNOŚĆ:** [np. 100% / 80%]
                * **Wykryte Measurement ID (tid):** `[Wypisz wszystkie unikalne G-XXXXXXXXXX]`

                ---
                ### 📋 Kontrola Reguł Analitycznych

                **Reguły Krytyczne (Twarde - dają 100% pewności):**
                * [✅/❌] **Liczba parametrów > 25 w evencie** (Wykryto maks: [X])
                * [✅/❌] **Długość wartości parametru NIESTANDARDOWEGO > 100 znaków** (Najdłuższy niestandardowy: [X] znaków, natywne pominięto)
                * [✅/❌] **Właściwości użytkownika > 25** (Wykryto maks: [X])
                * [✅/❌] **Niestandardowe parametry produktu (item-scoped) > 10** (Wykryto maks: [X] w jednym produkcie)

                **Reguły Kontekstowe (Miękkie - poszlaki biznesowe / wymagające weryfikacji API):**
                * [✅/❌] **Suma unikalnych parametrów w sesji > 50** (Wykryto łącznie: [X] - wymaga potwierdzenia rejestracji w Admin API)
                * [✅/❌] **Server-Side Tagging (Endpoint w 1st-party domain)** (Wykryto domenę: [Wpisz domenę])
                * [✅/❌] **Korporacyjny Multi-tagging** (Zdarzenia lecą do wielu `tid`)
                * [✅/❌] **Ekosystem Google Marketing Platform** (Wykryto tagi Floodlight / DoubleClick: [Tak/Nie])

                ---
                ### 🔍 Techniczne Uzasadnienie
                [Krótkie podsumowanie dlaczego wydałeś taki werdykt z uwzględnieniem faktu rygorystycznego odrzucenia parametrów natywnych typu page_location].
                """

                # Wysłanie danych do modelu
                response = model.generate_content([system_prompt, har_content])
                
                # Wyświetlenie wyniku
                st.success("Analiza zakończona sukcesem!")
                st.markdown(response.text)

            except Exception as e:
                st.error(f"❌ Wystąpił błąd podczas przetwarzania pliku: {e}")

# ==========================================
# ZAKŁADKA 2: SEKCJA EDUKACYJNA (EDU)
# ==========================================
with tab2:
    st.title("📚 Baza Wiedzy Analitycznej & Biznesowej")
    st.markdown("Zrozumienie reguł walidacyjnych stosowanych przez Detektywa. Dowiedz się, skąd biorą się limity i jak interpretować wyniki podczas rozmów handlowych.")
    
    st.info("💡 **Dla kogo jest ta sekcja?** Dla handlowców (przygotowanie do cold callu) oraz analityków pragnących zweryfikować techniczne aspekty działania algorytmu.")

    # --- KATEGORIA: REGUŁY TWARDE ---
    st.header("🔴 Reguły Krytyczne (Twarde)")
    st.markdown("Opierają się na oficjalnych, sztywnych limitach technologicznych nałożonych przez Google na darmową wersję GA4. Jeśli którakolwiek z tych reguł zostanie oznaczona jako ✅, strona **musi** posiadać płatną wersję GA360.")
    
    with st.expander("1. Liczba parametrów > 25 w pojedynczym evencie"):
        st.markdown("""
        * **Logika techniczna:** Agent szuka pojedynczego hitu (np. kliknięcie baneru) i zlicza parametry zaczynające się od `ep.` (tekstowe) oraz `epn.` (numeryczne).
        * **Uzasadnienie limitu:** Darmowe GA4 pozwala na maksymalnie **25** takich parametrów w jednym zdarzeniu. Wersja GA4 360 podnosi ten limit do **100**.
        * **Przykład w logach:** Jeśli zdarzenie `view_item` wysyła parametry od `ep.parametr_1` aż do `ep.parametr_28` (np. kolor, rozmiar, dostępność, magazyn, ID dostawcy itp.), darmowa wersja by je ucięła.
        """)

    with st.expander("2. Długość wartości parametru niestandardowego > 100 znaków (⚠️ Uwaga na wyjątki natywne)"):
        st.markdown("""
        * **Logika techniczna:** Agent mierzy liczbę znaków w wartościach parametrów, ale skupia się wyłącznie na parametrach **niestandardowych** (custom).
        * **Uzasadnienie limitu:** W darmowym GA4 każda wartość parametru *custom* (tekstowego) jest bezwzględnie ucinana po osiągnięciu **100 znaków**. GA4 360 pozwala na przesyłanie aż **500 znaków**.
        * **Dlaczego ignorujemy page_location / page_title / page_referrer?** Google wprowadziło oficjalne wyjątki dla swoich wbudowanych parametrów. W darmowej wersji `page_title` może mieć do 300 znaków, `page_referrer` do 420 znaków, a adres URL (`page_location`) aż do 1000 znaków. Przekroczenie 100 znaków w adresie URL jest rzeczą naturalną i nie świadczy o licencji Enterprise. Dopiero przekroczenie 100 znaków w parametrze autorskim (np. `ep.internal_search_term`) jest dowodem na GA360.
        """)

    with st.expander("3. Właściwości użytkownika (User Properties) > 25"):
        st.markdown("""
        * **Logika techniczna:** Agent zlicza parametry z przedrostkiem `up.` lub `upn.`, które opisują stałe cechy zalogowanego użytkownika w ramach sesji.
        * **Uzasadnienie limitu:** Standardowe GA4 ma sztywny limit **25** zarejestrowanych wymiarów na poziomie użytkownika. GA4 360 rozszerza ten limit do **100**.
        * **Przykład w logach:** Duże systemy CRM przekazują w sesji mnóstwo cech klienta (np. status VIP, segment zakupowy, rok rejestracji, preferowana kategoria). Przekroczenie 25 takich właściwości w logach jednoznacznie demaskuje licencję Enterprise.
        """)

    with st.expander("4. Niestandardowe parametry produktu (Item-scoped) > 10"):
        st.markdown("""
        * **Logika techniczna:** Agent zagląda do obiektów e-commerce reprezentujących produkty (tablice `pr1`, `pr2` itp.) i liczy unikalne parametry niestandardowe przypisane do pojedynczego przedmiotu.
        * **Uzasadnienie limitu:** Dla parametrów na poziomie produktu (item-scoped custom dimensions) darmowy limit to **10**. Wersja płatna GA360 pozwala na wdrożenie aż **25** takich atrybutów.
        * **Przykład w logach:** Rozbudowane e-commerce przekazują specyficzne cechy produktu bezpośrednio w obiekcie zakupowym, np. marżowość, ID producenta, status promocji, kod magazynowy, gabaryty. Wykrycie więcej niż 10 cech w jednym obiekcie produktu daje pewność licencji Enterprise.
        """)

    st.write("") # Odstęp wizualny

    # --- KATEGORIA: REGUŁY MIĘKKIE ---
    st.header("🟡 Reguły Kontekstowe (Miękkie / Poszlaki)")
    st.markdown("Te reguły nie wynikają bezpośrednio z blokad technicznych w kodzie front-endowym, ale niosą potężny ładunek informacji biznesowej. Spełnienie tych kryteriów oznacza, że firma operuje budżetami i architekturą klasy Enterprise.")

    with st.expander("1. Suma unikalnych parametrów w sesji > 50"):
        st.markdown("""
        * **Logika techniczna:** Agent analizuje cały plik HAR zbiorczo i wyciąga listę unikalnych nazw parametrów `ep.*` ze wszystkich zarejestrowanych hitów.
        * **Uzasadnienie limitu:** W bezpłatnym GA4 limit zarejestrowanych wymiarów niestandardowych wynosi **50** (w 360 rośnie do **125**). 
        * **Dlaczego to MIĘKKA poszlaka:** Limit dotyczy *aktywnej rejestracji* w panelu admina, a nie samej wysyłki sieciowej. Kod strony może słać 70 unikalnych nazw parametrów, ale jeśli w panelu włączono tylko 30 z nich, witryna nadal poprawnie działa na darmowym GA4. Wykrycie $>50$ parametrów w pliku HAR oznacza potężne skomplikowanie analityczne i potrzebę licencji 360, ale pełną weryfikację daje dopiero audyt przez GA4 Admin API (`customDimensions.list`).
        """)

    with st.expander("2. Server-Side Tagging (Punkt zbiórki w domenie 1st-party)"):
        st.markdown("""
        * **Logika techniczna:** Agent sprawdza hosta w adresach URL żądań. Jeśli ruch nie idzie bezpośrednio do `analytics.google.com` ani `google-analytics.com`, lecz na subdomenę klienta (np. `analityka.sklep.pl/g/collect`), wykrywane jest rozwiązanie serwerowe.
        * **Uzasadnienie biznesowe:** Konfiguracja i utrzymanie Google Tag Manatela w wersji Server-Side wymaga stałego opłacania chmury (np. Google Cloud Platform). Przy dużym ruchu e-commerce to koszt rzędu tysięcy złotych miesięcznie. Firmy inwestujące w tak zaawansowaną infrastrukturę ochrony danych rzadko kiedy zostają przy limitowanym, darmowym GA4.
        """)

    with st.expander("3. Korporacyjny Multi-tagging"):
        st.markdown("""
        * **Logika techniczna:** Agent zlicza unikalne identyfikatory pomiaru w parametrach `tid=` (zaczynające się od `G-`).
        * **Uzasadnienie biznesowe:** Wysyłanie tych samych danych równolegle do kilku różnych kont GA4 charakteryzuje duże struktury holdingowe lub międzynarodowe (np. jeden tag dla rynku lokalnego, drugi zbiorczy dla globalnej centrali). Małe firmy unikają tej praktyki z powodu generowania chaosu i podwójnego zużycia zasobów.
        """)

    with st.expander("4. Ekosystem Google Marketing Platform (Floodlight)"):
        st.markdown("""
        * **Logika techniczna:** Agent analizuje żądania sieciowe kierowane do domeny `doubleclick.net` w poszukiwaniu tagów konwersji Floodlight (parametry typu `src=`, `type=`, `cat=`).
        * **Uzasadnienie biznesowe:** Tagi Floodlight są natywnym elementem płatnego ekosystemu reklamowego korporacji (Campaign Manager 360, Display & Video 360, Search Ads 360). Its obecność to jasny sygnał, że firma realizuje wielomilionowe budżety reklamowe w systemach programatycznych – co niemal w 95% przypadków idzie w parze z licencją GA360 w celu pełnej analityki omnichanelowej.
        """)
