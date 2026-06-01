import streamlit as st
import google.generativeai as genai
import json

# Konfiguracja głównej strony aplikacji
st.set_page_config(page_title="Detektyw GA360", page_icon="🕵️‍♂️", layout="centered")

# --- BRAMKA BEZPIECZEŃSTWA ---
# Zmień to hasło na własne, które podasz zespołowi
HASLO_DOSTEPOWE = "MojaTajnaFirma2026" 

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

# --- INTERFEJS GŁÓWNY ---
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
                
                # POPRAWKA: Łapiemy GA4 ORAZ systemy DoubleClick/Floodlight/GMP
                if "collect" in url or "google-analytics" in url or "doubleclick" in url:
                    filtered_requests.append({
                        "url": url,
                        "query_string": entry["request"].get("queryString", []),
                        "post_data": entry["request"].get("postData", {}).get("text", "")
                    })
                
                # TWARDA BLOKADA: Pobieramy tylko pierwsze 25 żądań (zwiększone z 15, aby pomieścić DoubleClick)
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
            2. TWARDA REGUŁA 2: Długość wartości jakiegokolwiek parametru > 100 znaków.
            3. TWARDA REGUŁA 3: Liczba właściwości użytkownika 'up.' lub 'upn.' w sesji > 25.
            4. TWARDA REGUŁA 4: Suma UNIKALNYCH nazw parametrów 'ep.' ze wszystkich żądań łącznie > 50.
            5. TWARDA REGUŁA 5: Zlicz unikalne, niestandardowe parametry zdefiniowane na poziomie pojedynczego produktu (item-scoped, wewnątrz obiektów pr1, pr2 itp.). Jeśli dla jednego produktu jest ich > 10 -> WERDYKT GA360 (100%).
            6. MIĘKKA POSZLAKA 1: Server-Side Tagging (SSGTM). Sprawdź adres URL żądań. Jeśli żądania idą na domenę/subdomenę inną niż oficjalne serwery Google (nie analytics.google.com, nie google-analytics.com, nie doubleclick.net), oznacza to serwer pośredniczący.
            7. MIĘKKA POSZLAKA 2: Wykrycie wielu identyfikatorów 'tid' (Multi-tagging do kilku G-...).
            8. MIĘKKA POSZLAKA 3: Ślady integracji z Google Marketing Platform. Szukaj żądań zawierających w URL frazę 'doubleclick' oraz specyficznych znaczników dla tagów Floodlight (np. aktywności typu 'activity', parametry 'src=', 'type=', 'cat=' służące do raportowania konwersji w Campaign Manager 360 / DV360).

            Zwróć odpowiedź w czystym Markdown, dokładnie w formacie:
            ### 📊 Wynik analizy Google Analytics
            * **WERDYKT:** [GA 360 / Darmowe GA4 / Prawdopodobnie GA 360]
            * **PEWNOŚĆ:** [np. 100% / 80%]
            * **Wykryte Measurement ID (tid):** `[Wypisz wszystkie unikalne G-XXXXXXXXXX]`

            ---
            ### 📋 Kontrola Reguł Analitycznych

            **Reguły Krytyczne (Twarde - dają 100% pewności):**
            * [✅/❌] **Liczba parametrów > 25 w evencie** (Wykryto maks: [X])
            * [✅/❌] **Długość wartości parametru > 100 znaków** (Najdłuższy: [X] znaków)
            * [✅/❌] **Właściwości użytkownika > 25** (Wykryto maks: [X])
            * [✅/❌] **Suma unikalnych parametrów w sesji > 50** (Wykryto łącznie: [X])
            * [✅/❌] **Niestandardowe parametry produktu (item-scoped) > 10** (Wykryto maks: [X] w jednym produkcie)

            **Reguły Kontekstowe (Miękkie - poszlaki biznesowe):**
            * [✅/❌] **Server-Side Tagging (Endpoint w 1st-party domain)** (Wykryto domenę: [Wpisz domenę])
            * [✅/❌] **Korporacyjny Multi-tagging** (Zdarzenia lecą do wielu `tid`)
            * [✅/❌] **Ekosystem Google Marketing Platform** (Wykryto tagi Floodlight / DoubleClick: [Tak/Nie])

            ---
            ### 🔍 Techniczne Uzasadnienie
            [Krótkie podsumowanie dlaczego wydałeś taki werdykt].
            """

            # Wysłanie danych do modelu
            response = model.generate_content([system_prompt, har_content])
            
            # Wyświetlenie wyniku
            st.success("Analiza zakończona sukcesem!")
            st.markdown(response.text)

        except Exception as e:
            st.error(f"❌ Wystąpił błąd podczas przetwarzania pliku: {e}")
