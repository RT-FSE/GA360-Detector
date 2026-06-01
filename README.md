# 🕵️‍♂️ Dokumentacja Techniczna: Detektyw GA360 (Engine & Logic)

Narzędzie służy do pasywnej identyfikacji wersji usługi Google Analytics 4 (Standard vs 360 Enterprise) na podstawie analizy logów sieciowych klienta. Aplikacja działa w architekturze **Serverless** i opiera się na trzech filarach: **Streamlit** (interfejs użytkownika), **Python** (wstępna ekstrakcja i redukcja szumu) oraz **Gemini 3.5 Flash** (silnik heurystyczny LLM).

---

## 🏗️ 1. Architektura i Przepływ Danych (Data Flow)

Wgrywany plik `.har` (HTTP Archive) to w rzeczywistości potężny obiekt JSON zawierający pełną historię zapytań HTTP/HTTPS wygenerowanych podczas sesji przeglądarki. Ponieważ surowe pliki HAR potrafią ważyć od kilkunastu do kilkudziesięciu megabajtów (co paraliżowałoby okno kontekstowe API), aplikacja stosuje **dwustopniowy potok przetwarzania (Pipeline)**:

### Krok A: Parsowanie i redukcja szumu (Python Backend)

Zanim dane trafią do modelu LLM, skrypt filtruje obiekt JSON, bezwzględnie odrzucając zapytania o obrazy, skrypty, czcionki i CSS.

* **Reguła filtrowania:** Do pamięci RAM serwera dopuszczane są wyłącznie rekordy, których adres URL zawiera frazy: `collect`, `google-analytics` lub `doubleclick`.
* **Zabezpieczenie Rate-Limiting:** Skrypt pobiera maksymalnie **25 pierwszych hitów** spełniających kryteria. Zabezpiecza to aplikację przed błędem `HTTP 429 (Quota Exceeded)` w darmowym planie Google AI Studio (limit 250k tokenów/min).
* **Payload wyjściowy:** Z każdego zapytania izolowane są trzy klucze: surowy `url` (do analizy domenowej), struktura `queryString` (parametry w GET) oraz `postData` (parametry przesyłane w POST, np. przy beaconach batched events).

### Krok B: Ewaluacja heurystyczna (LLM Engine)

Odchudzony, czysty obiekt JSON w formacie tekstowym jest parowany z restrykcyjnym **Promptem Systemowym** i przesyłany do modelu `gemini-3.5-flash`. Model działa jako deterministyczny parser – jego zadaniem jest konwersja surowych ciągów zapytania na wskaźniki liczbowe i logiczne.

---

## ⚙️ 2. Specyfikacja Reguł Walidacyjnych (Front-End vs Panel Admina)

Narzędzie celowo operuje wyłącznie na danych **front-endowych** (mierzalnych z poziomu przeglądarki). Poniższa tabela przedstawia mapowanie techniczne limitów Google dla analityków:

| Identyfikator | Nazwa reguły | Typ | Limit GA4 Standard | Limit GA4 360 | Sygnatura w Payloadzie sieciowym |
| --- | --- | --- | --- | --- | --- |
| **TR_01** | Event Parameters Count | Twarda | Max 25 / event | Max 100 / event | Liczba unikalnych kluczy `ep.*` oraz `epn.*` w jednym żądaniu `/collect` |
| **TR_02** | Parameter Value Length | Twarda | Max 100 znaków | Max 500 znaków | Długość stringa (wielkość w bajtach) dla dowolnej wartości parametru |
| **TR_03** | User Properties Count | Twarda | Max 25 / sesję | Max 100 / sesję | Liczba unikalnych kluczy `up.*` oraz `upn.*` w sesji |
| **TR_04** | Global Custom Dimensions | Twarda | Max 50 / sesję | Max 125 / sesję | Suma unikalnych nazw parametrów `ep.*` zarejestrowanych w całym pliku HAR |
| **TR_05** | Item-scoped Dimensions | Twarda | Max 10 / produkt | Max 25 / produkt | Liczba niestandardowych parametrów w obiektach produktów (zagnieżdżone struktury `prX`) |
| **MP_01** | Server-Side Tagging | Miękka | N/A | N/A | Host żądania `/collect` różny od `analytics.google.com` (First-Party Endpoint) |
| **MP_02** | Multi-tagging Architecture | Miękka | N/A | N/A | Obecność $>1$ unikalnej wartości w parametrze `tid=` w ramach jednej sesji |
| **MP_03** | GMP Floodlight Integration | Miękka | N/A | N/A | Żądania do `doubleclick.net` zawierające endpointy `/activity` oraz query `src=`, `type=`, `cat=` |

---

## 🔬 3. Głęboka Analiza Sygnatur Sieciowych (Cheat-sheet dla Analityka)

Podczas manualnej weryfikacji raportu wygenerowanego przez bota, analityk powinien zwracać uwagę na następujące wzorce w surowym kodzie:

### 1. Detekcja Item-Scoped Custom Dimensions (TR_05)

W żądaniach GA4 e-commerce, produkty przesyłane są w formacie upakowanym. Standardowe parametry (np. ID, cena) mają swoje predefiniowane klucze. Custom dimensions na poziomie produktu są doklejane dynamicznie. Model LLM ma za zadanie sprasować obiekt produktu i zweryfikować, czy liczba niestandardowych kluczy przypisanych do `pr1` (lub kolejnych) przekracza 10.

### 2. First-Party Endpoint vs Reverse Proxy (MP_01)

Samo wykrycie, że domena żądania to np. `tracking.sklep.pl` potwierdza implementację **Server-Side Tagging**. Analityk musi pamiętać, że mniejsze firmy mogą używać SGTM do ominięcia AdBlocków w darmowym GA4. Dlatego ta reguła jest klasyfikowana jako **Miękka (Poszlaka)** – wysokie prawdopodobieństwo GA360 występuje wtedy, gdy First-Party Endpoint idzie w parze z gigantycznym volumem ruchu i zaawansowanym e-commerce (ze względu na wysokie koszty utrzymania instancji Google Cloud Platform / App Engine).

### 3. Ekosystem GMP (MP_03)

Wdrożenie tagów Floodlight bezpośrednio w kodzie (lub przez GTM) i mapowanie ich z parametrami konwersji jednoznacznie wskazuje na korzystanie z **Campaign Manager 360** lub **Display & Video 360**. Narzędzie przekazuje te żądania do Gemini, ponieważ korelacja między posiadaniem budżetów na systemy reklamowe GMP 360 a posiadaniem licencji GA360 wynosi blisko 95%.

---

## ⚠️ 4. Granice Możliwości Narzędzia (Known Limitations)

Narzędzie **nie analizuje i nie wykrywa** następujących limitów Enterprise, ponieważ nie zostawiają one śladów w strumieniu danych z przeglądarki (są procesowane po stronie backendu Google):

1. **Retencji danych (Data Retention):** Limit 14 vs 50 miesięcy jest ustawieniem retencyjnym baz danych GA4 i nie modyfikuje struktury hitu wychodzącego z serwera.
2. **Limitów eksportu do BigQuery (BQ Daily Export Limit):** Informacja o tym, czy usługa przekracza limit 1 miliona zdarzeń i przechodzi w tryb eksportu bez limitu (GA360), jest nieweryfikowalna pasywnie.
3. **Metryk kalkulowanych (Calculated Metrics):** Metryki te są wyliczane w locie podczas generowania raportów w interfejsu GA4 UI na podstawie standardowych parametrów.
