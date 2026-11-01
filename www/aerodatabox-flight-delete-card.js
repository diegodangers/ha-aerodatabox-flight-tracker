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
    // Store the form state across Home Assistant sensor refreshes.
    this._draft ||= { flight: "", date: "", travelers: [], phones: null, alexas: null, tv_services: null };
    const form = document.createElement("form");
    form.style.cssText = "display:grid;gap:10px;padding:12px;border:1px solid var(--divider-color);border-radius:10px";
    const title = document.createElement("strong");
    title.textContent = "Add Flight";
    const number = document.createElement("input");
    number.placeholder = "Flight number (e.g. DL389)";
    number.required = true;
    number.value = this._draft.flight;
    number.style.cssText = "padding:10px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)";
    number.addEventListener("input", () => { this._draft.flight = number.value; });
    const date = document.createElement("input");
    date.type = "date";
    date.required = true;
    date.value = this._draft.date;
    date.style.cssText = number.style.cssText;
    date.addEventListener("input", () => { this._draft.date = date.value; });
    const travelers = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = "Travelers";
    travelers.append(legend);
    const people = Object.values(this._hass.states)
      .filter(state => state.entity_id.startsWith("person."))
      .sort((a,b) => a.attributes.friendly_name.localeCompare(b.attributes.friendly_name));
    for (const person of people) {
      const label = document.createElement("label");
      label.style.cssText = "display:inline-flex;align-items:center;gap:6px;margin:4px 12px 4px 0";
      const check = document.createElement("input");
      check.type = "checkbox";
      check.checked = this._draft.travelers.includes(person.entity_id);
      check.addEventListener("change", () => {
        const selected = new Set(this._draft.travelers);
        if (check.checked) selected.add(person.entity_id);
        else selected.delete(person.entity_id);
        this._draft.travelers = [...selected];
      });
      label.append(check, document.createTextNode(person.attributes.friendly_name || person.entity_id));
      travelers.append(label);
    }
    // Choices are derived from configured flight recipients and available entities.
    const saved = flights.map(f => f.attributes.alert_recipients || {});
    const unique = key => [...new Set(saved.flatMap(r => r[key] || []))];
    const choices = {
      phones: [...new Set([...unique("phones"), ...Object.keys(this._hass.states).filter(id => id.startsWith("notify."))])],
      alexas: unique("alexas"),
      tv_services: unique("tv_services")
    };
    const notifications = document.createElement("fieldset");
    const notifyLegend = document.createElement("legend");
    notifyLegend.textContent = "Who should receive alerts?";
    notifications.append(notifyLegend);
    for (const [key, heading] of [["phones", "Phones"], ["alexas", "Alexa"], ["tv_services", "TVs"]]) {
      const group = document.createElement("div");
      group.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;margin:8px 0";
      const labelHeading = document.createElement("strong");
      labelHeading.textContent = heading + ":";
      group.append(labelHeading);
      const targets = choices[key];
      if (this._draft[key] === null) this._draft[key] = [...targets];
      for (const id of targets) {
        const label = document.createElement("label");
        label.style.cssText = "display:inline-flex;align-items:center;gap:5px";
        const check = document.createElement("input");
        check.type = "checkbox";
        check.checked = this._draft[key].includes(id);
        check.addEventListener("change", () => {
          const selection = new Set(this._draft[key]);
          if (check.checked) selection.add(id); else selection.delete(id);
          this._draft[key] = [...selection];
        });
        const display = this._hass.states[id]?.attributes?.friendly_name || id.replace(/^notify\\./, "").replace(/_/g, " ");
        label.append(check, document.createTextNode(display));
        group.append(label);
      }
      if (!targets.length) {
        const empty = document.createElement("span");
        empty.textContent = "No configured targets";
        group.append(empty);
      }
      notifications.append(group);
    }
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Add Flight";
    save.style.cssText = "padding:10px;border:1px solid var(--divider-color);border-radius:8px;cursor:pointer";
    form.append(title, number, date, travelers, notifications, save);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const flight_number = this._draft.flight.toUpperCase().replace(/\s+/g, "");
      const departure_date = this._draft.date;
      if (!/^[A-Z0-9]{2,3}[0-9]{1,5}[A-Z]?$/.test(flight_number) || !/^\d{4}-\d{2}-\d{2}$/.test(departure_date)) {
        window.alert("Enter a valid flight number and departure date.");
        return;
      }
      if (!this._draft.travelers.length) {
        window.alert("Select at least one traveler.");
        return;
      }
      save.disabled = true;
      save.textContent = "Saving…";
      try {
        await this._hass.callService("aerodatabox_flights", "save_flight", {
          flight_number, date: departure_date, travelers: this._draft.travelers
        }, {}, true, true);
        await this._hass.callService("aerodatabox_flights", "set_flight_alert_recipients", {
          flight_number, date: departure_date,
          phones: this._draft.phones || [],
          alexas: this._draft.alexas || [],
          tv_services: this._draft.tv_services || []
        }, {}, true, true);
        this._draft = {flight:"",date:"",travelers:[],phones:null,alexas:null,tv_services:null};
        this._render();
      } catch (err) {
        window.alert("Unable to save flight: " + (err?.message || String(err)));
        save.disabled = false;
        save.textContent = "Add Flight";
      }
    });
    this._body.append(form);
    if (!flights.length) {
      const empty = document.createElement("div");
      empty.textContent = "No saved flights.";
      this._body.append(empty);
      return;
    }
    const active = flights.filter(s => !s.attributes.finalized_at && !["landed", "canceled", "cancelled"].includes(String(s.state).toLowerCase()));
    const activeHeading = document.createElement("strong");
    activeHeading.textContent = "Upcoming / Active (" + active.length + ")";
    this._body.append(activeHeading);
    if (!active.length) {
      const empty = document.createElement("div");
      empty.textContent = "No active flights.";
      this._body.append(empty);
    }
    for (const state of active) {
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
          }, {}, true, true);
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
          }, {}, true, true);
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
  name: "AeroDataBox Flight Manager",
  description: "Confirm before deleting a saved flight from AeroDataBox history."
});
