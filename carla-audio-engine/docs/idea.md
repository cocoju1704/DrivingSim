Idee: 
---
Alle Banks in eine **einzige** Klasse Bank
Alles, was geladen werden muss wird in der config-Datei definiert
Um alle Banks zu laden wird über eine Liste dieser iteriert.

Bei dieser Idee müsste man also globale Parameter und instanzparam beachten
ich bräuchte damit eine Liste der zuordnung welcher Parameter zu welcher Instanz
gehört bzw. ob er global ist.
Wenn die funktion set param(name, value) aufgerufen wird, muss erstens sicher sein,
dass es keine zwei parameter mit dem gleichen namen gibt, das wäre SEHR problematisch
der name müsste dann mit der liste abgeglichen werden und je nach parametername würde dann
entweder studio_system.set_parameter_by_name oder event_instance.set...

Aus den Bank dateien könnten die entsprechenden Parameter rausgelesen werden und überprüft
werden ob sie global oder zum event gehören.

Diese Idee würde den Vorteil bringen, dass die Bank Klasse praktisch nicht mehr
"gepflegt" werden müsste, sondern alles automatisiert abläuft, durch skripte, die man bspw.
in der main aufgerufen werden.
Die Bank klasse könnte eine Methode haben wie "set_banks" und "receive_param" um alles nötige
zu erhalten.

Erstmal mit verschiedenen Bank klassen probieren und dann mal refactorn und schauen

Es könnte interessant sein, folgende Werte zu publishen
| Event                     | Wert                 | Beschreibung                                                             |
| ------------------------- | -------------------- | ------------------------------------------------------------------------ |
| `event_started`           | Event-Name oder ID   | Signalisiert, dass ein Sound-Event gestartet wurde                       |
| `event_stopped`           | Event-Name oder ID   | Signalisiert, dass ein Event gestoppt wurde                              |
| `event_error`             | Fehlermeldung        | Wenn FMOD einen Fehler wirft                                             |
| `event_parameter_changed` | Parametername + Wert | Falls du dynamische Parameter im Event setzt                             |
| `bank_loaded`             | Bankname             | Optional, falls Monitoring benötigt                                      |
| `studio_updated`          | Timestamp / Counter  | Optional, falls Subscriber wissen wollen, dass Studio aktualisiert wurde |

# 💡 Feature Idea: Central Bank class

## 1. Motivation
This could be useful as at the moment we have several different Bank classes that have to maintained
Warum ist diese Idee sinnvoll?
Welches Problem wird gelöst?
Welcher Mehrwert entsteht?

---

## 2. Aktueller Stand
Wie funktioniert das System aktuell?
Welche Klassen / Module sind betroffen?
(z.B. MotorBank, EventBus, SimulationController)

---

## 3. Zielbild (Soll-Zustand)
Wie soll es am Ende funktionieren?
Beschreibe das Verhalten möglichst konkret.

Beispiel:
- Motorgeräusch reagiert dynamisch auf Drehzahl
- Wetter beeinflusst Wind-Sound kontinuierlich
- Honk nur bei Zustandswechsel

---

## 4. Technische Umsetzungsidee

### 4.1 Betroffene Module
- audio/banks/motor_bank.py
- audio/event_bus.py
- simulation/weather_controller.py

### 4.2 Neue Klassen / Änderungen
- Neue Klasse?
- Neue Events?
- Erweiterung bestehender Methoden?

### 4.3 Datenfluss
Beschreibe den Flow:

CARLA → EventBus → Bank → FMOD Event → Playback

---

## 5. Risiken / offene Fragen
- Performance?
- Race Conditions?
- Event-Überlappung?
- FMOD Parameter-Typ (discrete vs continuous)?

---

## 6. Erweiterungsmöglichkeiten
Was könnte später darauf aufbauen?

---

## 7. TODO
- [ ] Konzept validieren
- [ ] Architektur skizzieren (PlantUML)
- [ ] Prototype implementieren
- [ ] Testfälle definieren