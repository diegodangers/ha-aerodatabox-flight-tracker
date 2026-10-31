/* AeroDataBox saved-flight delete card.
 * Install as a Lovelace JavaScript module resource:
 * /local/aerodatabox-flight-delete-card.js
 */
class AerodataboxFlightDeleteCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() { return 3; }

  _render() {
    if (!this._hass) return;
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this._card.header = this._config?.title || "Manage saved flights";
      this._body = document.createElement("div");
      this._body.style.cssText = "padding:0 16px 16px;display:grid;gap:10px";
      this._card.append(this._body);
      this.replaceChildren(this._card);
    }
    const flights = Object.values(this._hass.states)
      .filter(s => s.entity_id.startsWith("sensor.flight_") &&
        s.attributes?.flight_number && s.attributes?.departure_date)
      .sort((a,b) => a.attributes.departure_date.localeCompare(b.attributes.departure_date));
    this._body.replaceChildren();
    if (!flights.length) {
      this._body.textContent = "No saved flights.";
      return;
    }
    for (const state of flights) {
      const f = state.attributes;
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:12px";
      const details = document.createElement("div");
      const heading = document.createElement("strong");
      heading.textContent = f.flight_number + " · " + f.departure_date;
      const route = document.createElement("div");
      route.style.cssText = "color:var(--secondary-text-color);font-size:0.85em";
      const m = f.metadata || {};
      route.textContent = (m.departure_airport || "?") + " → " + (m.arrival_airport || "?");
      details.append(heading, route);
      const button = document.createElement("button");
      button.textContent = "Delete";
      button.type = "button";
      button.setAttribute("aria-label", "Delete " + f.flight_number + " on " + f.departure_date);
      button.style.cssText = "background:transparent;color:var(--error-color);border:1px solid var(--divider-color);padding:8px 12px;border-radius:8px;cursor:pointer";
      button.addEventListener("click", async () => {
        const label = f.flight_number + " on " + f.departure_date +
          " (" + (m.departure_airport || "?") + " → " + (m.arrival_airport || "?") + ")";
        if (!window.confirm("Permanently delete " + label +
          "? This removes its flight history, mileage and airline statistics. This cannot be undone.")) return;
        button.disabled = true;
        button.textContent = "Deleting…";
        try {
          await this._hass.callService("aerodatabox_flights", "delete_flight", {
            flight_number: f.flight_number,
            date: f.departure_date
          });
          // The integration publishes changed states; leave UI refresh to HA.
        } catch (err) {
          window.alert("Flight deletion failed: " + (err?.message || String(err)));
          button.disabled = false;
          button.textContent = "Delete";
        }
      });
      const controls = document.createElement("div");
      controls.style.cssText = "display:flex;align-items:center;gap:8px;flex-wrap:wrap";
      const excluded = f.include_in_statistics === false;
      const statsButton = document.createElement("button");
      statsButton.type = "button";
      statsButton.textContent = excluded ? "Include in stats" : "Exclude from stats";
      statsButton.title = "Toggle this flight's contribution to counts and airline punctuality without deleting it";
      statsButton.style.cssText = "background:transparent;color:var(--primary-text-color);border:1px solid var(--divider-color);padding:8px;border-radius:8px;cursor:pointer";
      statsButton.addEventListener("click", async () => {
        statsButton.disabled = true;
        try {
          await this._hass.callService("aerodatabox_flights", "set_flight_statistics_included", {
            flight_number: f.flight_number, date: f.departure_date, included: excluded
          });
        } catch (err) {
          window.alert("Unable to change statistics: " + (err?.message || String(err)));
        } finally {
          statsButton.disabled = false;
        }
      });
      controls.append(statsButton, button);
      row.append(details, controls);
      this._body.append(row);
    }
  }
}
if (!customElements.get("aerodatabox-flight-delete-card")) {
  customElements.define("aerodatabox-flight-delete-card", AerodataboxFlightDeleteCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "aerodatabox-flight-delete-card",
  name: "AeroDataBox Flight Delete",
  description: "Confirm before deleting a saved flight from AeroDataBox history."
});
