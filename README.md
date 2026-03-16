# Multi-Agent Simulation

Symulacja bada, jak sieć agentów organizuje przetwarzanie informacji w procesie biznesowym na przykładzie klasyfikacji wiadomości email i ekstrakcji danych z załączników w ciągu jednego dnia operacyjnego.

Celem projektu jest zrozumienie, kiedy lokalnie decyzje agentów prowadzą do **globalnie dobrego porządku w procesie**, albo kiedy tworzą:

- centra (huby),
- przeciążenia,
- ukryte wąskie gardła (bottlenecks),
- nadmierną eskalację do człowieka,
- oraz lokalnie skuteczne, ale nieoptymalne globalnie ścieżki komunikacji.

Na końcu dokumentu zamieszczony jest słownik pojęć.

---

## Główna idea

Projekt traktuje system agentowy jako **sieć relacji**.

Zachodzące procesy w sieci są podzielone na trzy poziomy:

- **poziom lokalny** — kompetencje, koszt, czas, pewność (confidence), degradacja skuteczności (fatigue) pojedynczego agenta,
- **poziom relacyjny** — routing, trust, historyczny sukces, kolejki, przekazywanie zadań,
- **poziom makro** — KPI procesu, koncentracja ruchu, bottlenecks, emergencja, odporność.

Projekt zakłada, że:
- dobra lokalna decyzja nie zawsze daje dobry wynik globalnie,
- pamięć relacyjna (`warm start`) nie zawsze poprawia KPI,
- topologia relacji może być równie ważna jak jakość samego agenta.

---

## Jaki problem jest symulowany

Model reprezentuje uproszczony, ale biznesowo realistyczny proces:

1. Do systemu wpływa wiadomość e-mail.
2. Wiadomość może zawierać załączniki i dane niepełne lub niejednoznaczne.
3. Sieć agentów:
   - interpretuje kontekst,
   - klasyfikuje sprawę,
   - rozbija ją na podzadania,
   - ekstrahuje dane,
   - sprawdza wyniki,
   - scala odpowiedzi,
   - a trudne przypadki eskaluje do człowieka.
4. W trakcie działania powstają lokalne wzorce współpracy, przeciążenia i dominujące ścieżki routingu.

---

## Co projekt symulacja

Najważniejsze pytania badawcze:

- Czy sieć agentów samoorganizuje się w sposób korzystny dla biznesu?
- Czy trust poprawia wynik procesu, czy tylko utrwala lokalne przyzwyczajenia?
- Czy `warm start` prowadzi do lepszego porządku, czy do większej inercji systemu?
- Kiedy wysoka jakość końcowa wynika z autonomii agentów, a kiedy głównie z eskalacji do człowieka?
- Czy można wykrywać przeciążenie systemu wcześniej niż przez same KPI?

---

## Co oznacza emergencja w tym projekcie

Emergencja oznacza tutaj, że wzorce pracy systemu:

- nie są zapisane w jednej regule,
- nie są planowane centralnie,
- nie wynikają wyłącznie z „najlepszego agenta”,

ale powstają z wielu lokalnych interakcji.

Przykłady:
- kilka agentów przejmuje większość ruchu mimo symetrycznych parametrów,
- trust uczy się relacji, ale nie poprawia globalnych KPI,
- topologia i lokalne polityki tworzą trwałe bottlenecks,
- system utrzymuje jakość głównie dzięki człowiekowi.

---

## Dlaczego pojawia się tu ANT

Projekt jest inspirowany Actor-Network Theory (ANT), ale nie jest jej formalną implementacją.

ANT jest tu używana jako **rama interpretacyjna**: sprawczość w systemie nie należy wyłącznie do agentów software’owych, ale powstaje w relacjach między:

- agentami,
- zadaniami,
- wiadomościami i załącznikami,
- trustem,
- progami eskalacji,
- kolejkami,
- timeoutami,
- SLA,
- i człowiekiem jako warstwą interwencji.

Dzięki temu projekt można wykorzystać nie tylko jako symulację przepływu (workflow), ale również jako model **sieci socjo-technicznej**.

---

## Dlaczego pojawia się tu „termodynamika”

Projekt używa wskaźników inspirowanych fizyką statystyczną:

- `T_eff` — effective temperature (temperatura),
- `U_eff` — effective internal energy (energia wewnętrzna),
- `S_eff` — effective entropy (entropia),
- `F_eff` — effective free energy (energia swobodna).

Nie są to ścisłe wielkości fizyczne. To **operacyjne analogie** do monitoringu systemu:

- `T_eff` — temperatura odzwierciedla poziom fluktuacji i niepewności,
- `U_eff` — energia wewnętrzna to napięcie operacyjne związane z kolejkami, reworkiem i SLA risk,
- `S_eff` — entropia jako miara nieuporządkowania pozwala oceniać rozproszenie tras i obciążenia,
- `F_eff` — energia swobodna to uproszczony potencjał organizacyjny układu.

Ich celem jest wykrywanie momentów, w których system:
- stabilizuje się,
- doświadcza przeciążenia,
- tworzy huby,
- lub zbliża się do punktu krytycznego.

---

## Dlaczego pojawia się tu Monte Carlo (MC)

Pojedynczy przebieg symulacji pokazuje, **jak może wyglądać jeden dzień operacyjny**, ale nie wystarcza to do oceny, czy obserwowany wzorzec jest:

- stabilną cechą architektury,
- czy tylko efektem konkretnej trajektorii zdarzeń.

Dlatego projekt wykorzystuje **Monte Carlo**.

W praktyce oznacza to, że ten sam scenariusz uruchamiany jest wielokrotnie przy różnych realizacjach losowych:
- napływu spraw,
- kolejności zdarzeń,
- lokalnych interakcji,
- oraz, w zależności od scenariusza, stanu pamięci relacyjnej.

Monte Carlo pełni w projekcie trzy funkcje:

### 1. Ocena stabilności wyników
MC pozwala odróżnić:
- pojedynczy incydent,
- od trwałej własności systemu.

Dzięki temu można sprawdzić, czy np.:
- huby pojawiają się regularnie,
- wysoka eskalacja do człowieka jest cechą architektury,
- wzrost `U_eff` lub zbliżanie się `F_eff` do zera jest powtarzalne.

### 2. Porównanie scenariuszy
MC umożliwia porównywanie wariantów:
- topologii sieci agentów,
- polityk routingu,
- reward dla trust (mechanizm aktualizacji zaufania między agentami po zakończeniu podzadania),
- `cold start` vs `warm start`,
- burstów (szczyt operacyjny), awarii i bottlenecków (wąskich gardeł).

Zamiast jednego przebiegu porównujemy wtedy:
- średnią trajektorię,
- medianę,
- percentyle,
- i rozrzut wyników między uruchomieniami.

### 3. Szersza perspektywa na „termodynamikę” systemu
Wskaźniki takie jak:
- `T_eff`,
- `U_eff`,
- `S_eff`,
- `F_eff`

mogą być analizowane nie tylko dla jednego uruchomienia, ale także jako **trajektorie uśrednione punkt po punkcie w czasie** po wielu przebiegach MC.

To pozwala odpowiedzieć na pytania:
- jak wygląda typowy dzień operacyjny,
- kiedy system zwykle wchodzi w strefę napięcia,
- czy `warm start` stabilizuje system,
- czy raczej utrwala lokalnie skuteczne, ale globalnie kosztowne ścieżki.

### Single run vs Monte Carlo
W projekcie obie perspektywy są potrzebne:

- **single run** — pokazuje mechanikę konkretnego dnia operacyjnego,
- **Monte Carlo** — pokazuje, czy dany wzorzec jest typowy, trwały i statystycznie wiarygodny.

Dlatego wyniki należy czytać równolegle:
- jako przebiegi jednego dnia,
- oraz jako rozkłady zachowania systemu w wielu uruchomieniach.

---

## Co nie jest celem projektu

Ten projekt nie jest:

- produkcyjnym frameworkiem agentowym,
- benchmarkiem konkretnego LLM-a,
- symulatorem ludzi,
- formalną teorią ANT,
- ani ścisłą teorią termodynamiczną systemów IT.

To jest **eksperymentalny model badawczy**, którego celem jest zrozumienie organizacji pracy systemów agentowych.

---

## Najważniejsze wyniki, których szukamy

Projekt pozwala badać, czy system:

- poprawia throughput (liczba spraw zamniętych w jednostce czasu) bez utraty jakości,
- utrzymuje SLA bez nadmiernej eskalacji,
- tworzy specjalizację zamiast hubów,
- uczy się relacji zgodnych z globalnym celem procesu,
- pozostaje odporny na bursty (szczyty operacyjne), awarie i degradację warstw wykonawczych.

---

## Słownik skrótów

- **ANT** — Actor-Network Theory  
- **Cold start** — uruchomienie bez pamięci relacyjnej i trust z poprzednich epizodów  
- **Confidence** — ocena pewności wyniku agenta  
- **Escalation** — przekazanie sprawy do człowieka  
- **Fatigue** — degradacja skuteczności agenta przy przeciążeniu  
- **Hub** — węzeł przejmujący nieproporcjonalnie dużą część ruchu  
- **KPI** — Key Performance Indicators  
- **MC** — metoda Monte Carlo  
- **Routing** — wybór kolejnego agenta lub ścieżki  
- **SLA** — Service Level Agreement  
- **T_eff** — effective temperature - temperatura
- **U_eff** — effective internal energy - energia wewnętrzna
- **S_eff** — effective entropy - entropia
- **F_eff** — effective free energy - energia swobodna
- **Timeout** — przekroczenie dopuszczalnego czasu oczekiwania lub obsługi  
- **Trust** — lokalna pamięć jakości relacji między agentami  
- **Warm start** — uruchomienie rozpoczynany ze stanem pamięci/trustu po wcześniejszych epizodach  

---

## Literatura

### Multi-Agent Systems
1. Dorri, A., Kanhere, S. S., & Jurdak, R. *Multi-Agent Systems: A Survey*, https://www.researchgate.net/publication/324847369_Multi-Agent_Systems_A_survey
2. Jin, W. et al. *A Comprehensive Survey on Multi-Agent Cooperative Decision-Making: Scenarios, Approaches, Challenges and Perspectives*, https://arxiv.org/abs/2503.13415
3. Wang, J. et al. *Resilient Consensus Control for Multi-Agent Systems*, https://www.researchgate.net/publication/369110552_Resilient_Consensus_Control_for_Multi-Agent_Systems_A_Comparative_Survey

### Agent-Based Simulation / Process Simulation
4. Bemthuis, R. H. et al. *Towards integrating process mining with agent-based modeling and simulation*, https://www.sciencedirect.com/science/article/pii/S0957417425011935
5. Schäfer, P. et al. *Context is all you need: Towards autonomous model-based process design using agentic AI in flowsheet simulations*, https://arxiv.org/abs/2603.12813

### ANT
6. Latour, B. *Reassembling the Social: An Introduction to Actor-Network-Theory*
7. Abriszewski, K. *Teoria Aktora-Sieci Bruno Latoura*, https://rcin.org.pl/Content/51075/WA248_67121_P-I-2524_abriszew-teoria.pdf

---

## Główna teza projektu

**System agentowy może lokalnie uczyć się sensownych relacji i jednocześnie nie poprawiać globalnej efektywności procesu.**

Dlatego architektura Agentic AI wymaga analizy nie tylko na poziomie pojedynczego agenta, ale także na poziomie:

- topologii relacji,
- pamięci organizacyjnej,
- przeciążenia,
- bottlenecków,
- i emergentnych wzorców pracy całej sieci.