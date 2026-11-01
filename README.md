<p align="center">
  <img src="custom_components/muenchner_stadtbibliothek/brand/icon.png" width="128" alt="Münchner Stadtbibliothek">
</p>

<h1 align="center">Münchner Stadtbibliothek</h1>

<p align="center">
  Bibliotheksausweis und Ausleihen der Münchner Stadtbibliothek in Home Assistant, mit Verlängerung per Knopfdruck.
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <a href="https://github.com/beatschubser/ha-muenchner-stadtbibliothek/releases"><img src="https://img.shields.io/github/v/release/beatschubser/ha-muenchner-stadtbibliothek?include_prereleases" alt="Release"></a>
  <a href="https://github.com/beatschubser/ha-muenchner-stadtbibliothek/actions/workflows/validate.yml"><img src="https://github.com/beatschubser/ha-muenchner-stadtbibliothek/actions/workflows/validate.yml/badge.svg" alt="Validate"></a>
</p>

> [!WARNING]
> **In Entwicklung.** Inoffizielle Integration, kein Angebot der Münchner Stadtbibliothek. Sie liest die Kontoseiten des Online-Katalogs. Ändert die Bibliothek diese Seiten, funktioniert die Integration möglicherweise erst nach einem Update wieder.

> [!NOTE]
> Der Code ist zu 100 % KI-generiert.

## Funktionen

- **Ausweis gültig bis** als Datumssensor.
- **Ausleihen** mit Fälligkeit, Bibliothek, Titel, Autor, Signatur, Mediennummer und dem Hinweis aus dem Katalog (z. B. „verlängerbar“, „Heute verlängert“).
- **Nächste Fälligkeit** mit den Titeln, die an diesem Tag fällig sind.
- **Ein Verlängern-Button pro Ausleihe.** Die Buttons erscheinen und verschwinden mit den Ausleihen. Nicht verlängerbare Medien werden gar nicht erst an den Katalog geschickt, der Button zeigt stattdessen den Grund.
- **Eigene Dashboard-Karte** mit Resttagen, Verlängern-Button und Auswahl zwischen mehreren Ausweisen.
- Mehrere Ausweise (z. B. einer pro Familienmitglied), jeder als eigenes Gerät mit eigenem Namen.
- Wenig Verkehr: Jede Aktualisierung ist eine kurze Katalog-Sitzung (Anmelden, Übersicht, Ausleihen, Abmelden), ohne Wiederholungen. Standardintervall 4 Stunden, einstellbar von 1 bis 48 Stunden.

## Installation

1. HACS → drei Punkte → **Benutzerdefinierte Repositories** → `https://github.com/beatschubser/ha-muenchner-stadtbibliothek` hinzufügen, Typ **Integration**.
2. **Münchner Stadtbibliothek** installieren und Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Münchner Stadtbibliothek**.
4. Name, Ausweisnummer und Passwort eingeben (wie im Online-Katalog). Der Name erscheint als Gerätename und in der Karte, z. B. der Vorname des Ausweisinhabers.

Das Aktualisierungsintervall lässt sich später unter **Konfigurieren** ändern. Weitere Ausweise fügst du über **Eintrag hinzufügen** hinzu.

## Dashboard-Karte

Die Integration bringt ihre eigene Karte mit und trägt sie automatisch als Dashboard-Ressource ein (nach Installation oder Update den Browser einmal neu laden).

**Dashboard bearbeiten → Karte hinzufügen → Münchner Stadtbibliothek.** Alle Optionen lassen sich im visuellen Editor einstellen, die Kartengröße im Layout-Tab:

| Option | Standard | |
| --- | --- | --- |
| `account` | alle | Name eines Ausweises (wie bei der Einrichtung vergeben oder als Gerät umbenannt). Ohne Angabe erscheinen alle Ausweise als Auswahl-Pillen |
| `title` | Name des Ausweises | Überschrift, wenn nur ein Ausweis angezeigt wird |
| `show_card` | `true` | „Ausweis gültig bis“ in der Kopfzeile |
| `show_library` | `true` | Bibliothek neben dem Autor |
| `max_width` | `640` | maximale Breite in px, zentriert (z. B. in Pop-ups); `0` = volle Breite |
| `card_warn_days` | `30` | ab so vielen Tagen vor Ablauf wird die Ausweis-Gültigkeit orange, ab 7 Tagen rot mit Hinweisbalken |
| `loan_days` | `28` | Leihfrist in Tagen, entspricht dem vollen Ring |
| `appearance` | `auto` | `auto` (Theme), `light`, `dark` |

```yaml
type: custom:muenchner-stadtbibliothek-card
account: Anna   # optional, der Name aus der Einrichtung
```

Sind mehrere Ausweise eingerichtet, zeigt die Karte oben eine Pille pro Name; ein Tipp wechselt die Ansicht. Für nur eine Person den Namen im Editor auswählen.

Jede Ausleihe zeigt die Resttage als Ring (orange ab 3 Tagen, rot wenn überfällig), Titel, Autor, Bibliothek und Fälligkeit. Verlängerbare Medien haben einen Button „Verlängern“, heute verlängerte ein grünes „Heute verlängert“; nicht verlängerbare Medien haben keinen Button. Während einer Verlängerung und 5 Sekunden nach einem Fehler ist der Button gesperrt. In schmalen Spalten zeigen die Buttons nur Icons. Läuft ein Ausweis bald ab, wird die Gültigkeit orange (30 Tage vorher) bzw. rot mit Hinweisbalken (7 Tage vorher); auch bei ausgeschalteter Gültigkeitsanzeige. Die Pille des betroffenen Ausweises bekommt einen farbigen Punkt.

## Entitäten

| Entität (deutscher / englischer Name) | Zustand | Attribute |
| --- | --- | --- |
| Ausweis gültig bis / Card valid until | Datum | |
| Ausleihen / Loans | Anzahl der Ausleihen | `loans` (Liste), `renewable`, `card_valid_until`, `last_update` |
| Nächste Fälligkeit / Next due date | Datum | `count`, `titles`, `renewable` |
| *Titel* verlängern / Renew *title* (Button) | | `barcode`, `title`, `author`, `full_title`, `signature`, `library`, `due_date`, `hint`, `renewable`, `renewed_today`, `renewals` |

Jeder Eintrag im Attribut `loans` hat dieselben Felder wie die Button-Attribute. Die Attributnamen sind englisch.

## Beispiele

Benachrichtigung aufs Smartphone, wenn Ausleihen in 7 bzw. 2 Tagen fällig sind und wenn ein Ausweis in 30 bzw. 7 Tagen abläuft, pro Ausweis und ohne Buchtitel:

```yaml
alias: Bibliothek - Fälligkeiten melden
triggers:
  - trigger: time
    at: "09:00:00"
variables:
  notify_targets:
    - notify.mobile_app_dein_handy
  days_ahead:
    - 7
    - 2
  card_days_ahead:
    - 30
    - 7
actions:
  - repeat:
      for_each: >
        {{ expand(integration_entities('muenchner_stadtbibliothek') | select('match', 'sensor\\.') | list)
           | selectattr('attributes.loans', 'defined')
           | map(attribute='entity_id') | list }}
      sequence:
        - variables:
            card_name: >
              {% set dev = device_id(repeat.item) %}
              {{ device_attr(dev, 'name_by_user') or device_attr(dev, 'name') }}
            message: >
              {% set loans = state_attr(repeat.item, 'loans') or [] %}
              {% set parts = namespace(list=[]) %}
              {% for n in days_ahead | sort %}
                {% set due = (now().date() + timedelta(days=n)) | string %}
                {% set count = loans | selectattr('due_date', 'eq', due) | list | count %}
                {% if count > 0 %}
                  {% set parts.list = parts.list + [count ~ (' Medium' if count == 1 else ' Medien') ~ ' in ' ~ n ~ ' Tagen fällig'] %}
                {% endif %}
              {% endfor %}
              {% set sentences = namespace(list=[]) %}
              {% if parts.list %}
                {% set sentences.list = [parts.list | join(', ') ~ '.'] %}
              {% endif %}
              {% set valid = state_attr(repeat.item, 'card_valid_until') %}
              {% if valid %}
                {% set left = (strptime(valid, '%Y-%m-%d').date() - now().date()).days %}
                {% if left in card_days_ahead %}
                  {% set sentences.list = sentences.list + ['Der Ausweis läuft in ' ~ left ~ ' Tagen ab.'] %}
                {% endif %}
              {% endif %}
              {{ sentences.list | join(' ') }}
        - condition: template
          value_template: "{{ message | length > 0 }}"
        - repeat:
            for_each: "{{ notify_targets }}"
            sequence:
              - action: "{{ repeat.item }}"
                data:
                  title: Bibliothek
                  message: "Ausweis {{ card_name }}: {{ message }}"
mode: single
```

Alles verlängern, was in den nächsten drei Tagen fällig ist (einmal täglich):

```yaml
triggers:
  - trigger: time
    at: "08:00:00"
actions:
  - variables:
      due: >
        {% set limit = (now().date() + timedelta(days=3)) | string %}
        {{ expand(integration_entities('muenchner_stadtbibliothek') | select('match', 'button\\.') | list)
           | selectattr('attributes.renewable', 'eq', true)
           | selectattr('attributes.due_date', 'le', limit)
           | map(attribute='entity_id') | list }}
  - condition: template
    value_template: "{{ due | count > 0 }}"
  - action: button.press
    target:
      entity_id: "{{ due }}"
```

## So funktioniert es

Der Katalog läuft mit aDIS/BMS. Die Integration verhält sich wie ein Nutzer im Browser: Sie meldet sich über das normale Login-Formular an, öffnet die Kontoübersicht und die Ausleihen und meldet sich wieder ab. Zum Verlängern setzt sie genau ein Häkchen und klickt einmal auf „Markierte Medien verlängern“; der neue Stand kommt direkt aus der Antwortseite. Jede Seite hat 10 Sekunden Zeit, es gibt keine automatischen Wiederholungen.

Ausweisnummer und Passwort liegen im Konfigurationseintrag von Home Assistant und werden nur an `ssl.muenchen.de` gesendet.
