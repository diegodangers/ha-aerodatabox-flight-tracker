# SkyLedger

Home Assistant flight tracking, travel history, notifications and airline reliability.

**Release candidate.** The integration domain is `skyledger`. New installations can install it through HACS as a custom repository after a release is published. **Existing `aerodatabox_flights` installations require an offline migration before upgrading**; see [migration instructions](docs/domain-migration.md). Installing the renamed package alone does not migrate saved configuration or history.

## Native configuration

After installing and restarting, open Settings → Devices & Services → SkyLedger →
Configure to set approved phone, Alexa/media player and TV notification recipients
and Alexa quiet hours. These defaults apply to **new flights only**; existing
flight-specific recipient settings are preserved. The optional Flight Manager card supports per-flight recipient selection. Automatic recipient discovery for newly added devices is planned but not yet implemented.

The schedule provider is currently AeroDataBox, and live tracking uses
[Flightradar24 by AlexandrErohin](https://github.com/AlexandrErohin/home-assistant-flightradar24).
SkyLedger checks for FR24 tracking entities on startup and every five minutes. Missing or
unavailable entities generate a Home Assistant notification with installation or configuration
guidance; the notification clears once FR24 becomes available. SkyLedger does not silently
install third-party integrations. Scheduling and saved history work without FR24. Provider independence is an architectural goal, not yet an
implemented provider-switching capability.

## Flights dashboard

The current user's Flights dashboard is a storage-mode Lovelace dashboard and is
**not automatically deployed** by the integration or by installing its Python
files. Existing dashboards remain as-is on upgrade. The optional Flight Manager
frontend is in `www/skyledger-flight-manager-card.js`. Copy it to
`/config/www/`, register it as a JavaScript module resource at
`/local/skyledger-flight-manager-card.js`, and add:

```yaml
type: custom:skyledger-flight-manager-card
title: Flight Manager
```

The rest of the existing Flights dashboard contains views/cards configured in
Home Assistant and is not bundled for automatic installation. A portable,
opt-in dashboard template is future work. Installing this integration must not
replace an existing user's Lovelace dashboard.

## Flight management

New installations use `skyledger` services. Existing `aerodatabox_flights` services remain on the old installation until migration, including `save_flight`, `delete_flight`, and
`set_flight_statistics_included`.
