/* SkyLedger compact Flight Manager — HA Lovelace custom card */
class SkyLedgerFlightManagerCard extends HTMLElement {
  setConfig(config) { this._config=config||{}; this.render(); }
  set hass(hass) {
    const old=this._hass; this._hass=hass;
    if (!old || old.states!==hass.states) {
      if (!this._busy && !this._formOpen) this.render();
      else this.refreshSummary();
    }
  }
  getCardSize() { return 3; }
  connectedCallback() { this.render(); }
  el(tag,cls,text) {
    const e=document.createElement(tag);
    if(cls)e.className=cls;
    if(text!==undefined)e.textContent=text;
    return e;
  }
  flights() {
    return Object.values(this._hass?.states||{}).filter(s=>s.entity_id.startsWith("sensor.flight_")&&s.attributes?.flight_number&&s.attributes?.departure_date)
      .sort((a,b)=>b.attributes.departure_date.localeCompare(a.attributes.departure_date));
  }
  refreshSummary() {
    if(!this._summary)return;
    const flights=this.flights();
    const active=flights.filter(s=>!s.attributes.finalized_at&&!["landed","canceled","cancelled"].includes(String(s.state).toLowerCase()));
    this._summary.textContent=`${active.length} upcoming · ${flights.length} saved`;
  }
  render() {
    if(!this.isConnected||!this._hass||this._busy||this._formOpen)return;
    if(!this._card) {
      this._card=this.el("ha-card");
      this._root=this.el("div","root");
      const style=this.el("style");
      style.textContent=`
        .root{padding:16px;color:var(--primary-text-color);font:inherit}
        .head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}
        .title{font-size:1.05rem;font-weight:650}.sub{font-size:.78rem;color:var(--secondary-text-color);margin-top:2px}
        button{font:inherit;cursor:pointer;border-radius:9px;min-height:34px}
        .primary{border:0;background:var(--primary-color);color:var(--text-primary-color,#fff);padding:7px 12px;font-weight:600}
        .secondary{background:transparent;color:var(--primary-text-color);border:1px solid var(--divider-color);padding:6px 10px}
        .danger{color:var(--error-color);background:transparent;border:1px solid var(--divider-color);padding:5px 9px}
        .flight{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:11px 0;border-top:1px solid var(--divider-color)}
        .flight-info{min-width:0;flex:1}.flight-number{font-weight:650;font-size:.93rem}
        .route{color:var(--secondary-text-color);font-size:.78rem;margin-top:3px}
        .actions{display:flex;align-items:center;gap:6px;flex-shrink:0}
        .section{font-size:.76rem;font-weight:650;color:var(--secondary-text-color);margin:14px 0 6px;text-transform:uppercase;letter-spacing:.035em}
        .empty{font-size:.85rem;color:var(--secondary-text-color);padding:12px 0}
        .form{border-top:1px solid var(--divider-color);padding-top:12px;margin-top:12px}
        .fields{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:10px 0}
        label.field{display:flex;flex-direction:column;gap:5px;font-size:.78rem;color:var(--secondary-text-color)}
        input[type=text],input[type=date]{box-sizing:border-box;width:100%;min-width:0;padding:9px;border:1px solid var(--divider-color);border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color);font:inherit;font-size:.88rem}
        .people{display:flex;gap:12px;flex-wrap:wrap;margin:9px 0 12px;font-size:.84rem}
        .people label{display:flex;gap:5px;align-items:center}
        .note{font-size:.75rem;color:var(--secondary-text-color);margin:8px 0}
        .footer{display:flex;justify-content:flex-end;gap:8px}
        .more{border:0;background:transparent;color:var(--secondary-text-color);padding:5px 7px}
        .menu{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end;margin-top:6px}
        button:disabled{opacity:.5;cursor:wait}
        @media(max-width:420px){.root{padding:12px}.fields{grid-template-columns:1fr 1fr}.flight{gap:5px}.actions{gap:3px}}
      `;
      this._card.append(style,this._root);this.replaceChildren(this._card);
    }
    const root=this._root;root.replaceChildren();
    const head=this.el("div","head"),left=this.el("div"),title=this.el("div","title",this._config.title||"Flight Manager");
    this._summary=this.el("div","sub");left.append(title,this._summary);
    const add=this.el("button","primary","+ Add flight");add.type="button";add.onclick=()=>this.openForm();
    head.append(left,add);root.append(head);this.refreshSummary();
    const flights=this.flights(),active=flights.filter(s=>!s.attributes.finalized_at&&!["landed","canceled","cancelled"].includes(String(s.state).toLowerCase()));
    const completed=flights.filter(s=>!active.includes(s));
    const section=(name,items,empty)=>{
      root.append(this.el("div","section",name));
      if(!items.length){root.append(this.el("div","empty",empty));return;}
      for(const state of items)this.renderFlight(root,state);
    };
    section("Upcoming & active",active,"No upcoming flights");
    section("History",completed,"No completed flights");
  }
  openForm(){
    if(this._formOpen)return;
    this._formOpen=true;
    const form=this.el("form","form");
    const heading=this.el("div","section","Add flight");form.append(heading);
    const fields=this.el("div","fields");
    const field=(label,type,placeholder)=>{
      const l=this.el("label","field",label),i=this.el("input");
      i.type=type;i.placeholder=placeholder||"";i.required=true;l.append(i);fields.append(l);return i;
    };
    const number=field("Flight number","text","DL2084"),date=field("Departure date","date");
    form.append(fields);
    form.append(this.el("div","section","Travelers"));
    const people=this.el("div","people");
    for(const person of Object.values(this._hass.states).filter(s=>s.entity_id.startsWith("person.")).sort((a,b)=>(a.attributes.friendly_name||"").localeCompare(b.attributes.friendly_name||""))){
      const label=this.el("label"),input=this.el("input");input.type="checkbox";input.value=person.entity_id;
      label.append(input,document.createTextNode(person.attributes.friendly_name||person.entity_id));people.append(label);
    }
    form.append(people,this.el("div","note","Alert defaults are configured in SkyLedger settings."));
    const footer=this.el("div","footer"),cancel=this.el("button","secondary","Cancel"),save=this.el("button","primary","Save flight");
    cancel.type="button";save.type="submit";cancel.onclick=()=>{this._formOpen=false;this.render();};
    footer.append(cancel,save);form.append(footer);
    form.onsubmit=async e=>{
      e.preventDefault();
      const flight_number=number.value.toUpperCase().replace(/\s+/g,""),day=date.value;
      const travelers=[...people.querySelectorAll("input:checked")].map(x=>x.value);
      if(!/^[A-Z0-9]{2,3}[0-9]{1,5}[A-Z]?$/.test(flight_number)||!/^\d{4}-\d{2}-\d{2}$/.test(day)){window.alert("Enter a valid flight number and date.");return;}
      if(!travelers.length){window.alert("Select at least one traveler.");return;}
      this._busy=true;save.disabled=true;save.textContent="Saving…";
      try{await this._hass.callService("skyledger","save_flight",{flight_number,date:day,travelers},{},true,true);this._formOpen=false;this._busy=false;this.render();}
      catch(err){this._busy=false;save.disabled=false;save.textContent="Save flight";window.alert("Unable to save flight: "+(err?.message||String(err)));}
    };
    this._root.insertBefore(form,this._root.children[1]||null);number.focus();
  }
  renderFlight(root,state){
    const f=state.attributes,m=f.metadata||{},row=this.el("div","flight"),info=this.el("div","flight-info");
    const date=f.departure_date,route=`${m.departure_airport||"?"} → ${m.arrival_airport||"?"}`;
    info.append(this.el("div","flight-number",`${f.flight_number} · ${date}`),this.el("div","route",route));
    const actions=this.el("div","actions"),more=this.el("button","more","•••");more.type="button";more.title="Flight actions";more.setAttribute("aria-label","Actions for "+f.flight_number);
    const menu=this.el("div","menu");menu.hidden=true;
    const excluded=f.include_in_statistics===false;
    const stats=this.el("button","secondary",excluded?"Include in stats":"Exclude from stats"),del=this.el("button","danger","Delete");
    for(const b of [stats,del])b.type="button";
    more.onclick=()=>{menu.hidden=!menu.hidden;};
    stats.onclick=async()=>{stats.disabled=true;try{await this._hass.callService("skyledger","set_flight_statistics_included",{flight_number:f.flight_number,date,included:excluded},{},true,true);menu.hidden=true;this.render();}catch(err){window.alert("Unable to update statistics: "+(err?.message||String(err)));}finally{stats.disabled=false;}};
    del.onclick=async()=>{
      if(!window.confirm(`Permanently delete ${f.flight_number} on ${date} (${route})? This removes its history and statistics and cannot be undone.`))return;
      del.disabled=true;del.textContent="Deleting…";
      try{await this._hass.callService("skyledger","delete_flight",{flight_number:f.flight_number,date},{},true,true);this.render();}
      catch(err){window.alert("Delete failed: "+(err?.message||String(err)));del.disabled=false;del.textContent="Delete";}
    };
    menu.append(stats,del);actions.append(more);row.append(info,actions);
    const wrap=this.el("div");wrap.append(row,menu);root.append(wrap);
  }
}
if(!customElements.get("skyledger-flight-manager-card"))customElements.define("skyledger-flight-manager-card",SkyLedgerFlightManagerCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==="skyledger-flight-manager-card"))window.customCards.push({type:"skyledger-flight-manager-card",name:"SkyLedger Flight Manager",description:"Compact flight management"});
