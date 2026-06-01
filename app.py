import streamlit as st
import google.generativeai as genai

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
            # Dekodowanie pliku HAR do zwykłego tekstu
            har_content = uploaded_file.getvalue().decode("utf-8")

            # --- PROMPT SYSTEMOWY DLA AGENTA ---
            system_prompt = """
            Jesteś technicznym ekspertem web analityki. Otrzymujesz surowy plik HAR. 
            Twoim zadaniem jest analiza żądań do '/collect' (Google Analytics 4) i ocena, czy strona korzysta z płatnej wersji GA360.

            Zastosuj rygorystyczne reguły decyzyjne:
            1. TWARDA REGUŁA 1: Policz unikalne parametry 'ep.' oraz 'epn.' w jednym zdarzeniu. Jeśli jest ich >25 -> WERDYKT: GA 360 (100%).
            2. TWARDA REGUŁA 2: Sprawdź długość znaków dla wartości parametrów. Jeśli jakakolwiek wartość przekracza 100 znaków -> WERDYKT: GA 360 (100%).
            3. POSZLAKA: Szukaj parametrów zaczynających się od 'sst.' (oznacza Server-Side Tagging). Jeśli jest SSGTM + bogaty e-commerce -> Prawdopodobnie GA 360.
            4. IDENTYFIKATOR: Zawsze wyciągaj i prezentuj identyfikator usługi z parametru 'tid' (zaczyna się od G-...).

            Zwróć odpowiedź w czystym Markdown, dokładnie w poniższym formacie:
            ### 📊 Wynik analizy Google Analytics
            * **WERDYKT:** [GA 360 / Darmowe GA4 / Prawdopodobnie GA 360]
            * **PEWNOŚĆ:** [np. 100% / 80%]
            * **Measurement ID (tid):** `[G-XXXXXXXXXX]`
            ---
            ### 🔍 Dowody z analizy sieciowej:
            * **Liczba parametrów w najdłuższym evencie:** [X]
            * **Najdłuższy parametr:** `ep.[nazwa]` = [X] znaków
            * **Server-Side Tagging:** [Tak/Nie]
            * **Krótkie uzasadnienie:** [1-2 zdania technicznego uzasadnienia Twojej decyzji]
            """

            # Wysłanie danych do modelu
            response = model.generate_content([system_prompt, har_content])
            
            # Wyświetlenie wyniku
            st.success("Analiza zakończona sukcesem!")
            st.markdown(response.text)

        except Exception as e:
            st.error(f"❌ Wystąpił błąd podczas przetwarzania pliku: {e}")