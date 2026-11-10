// SkyLedger active flight: compact details + OpenStreetMap/Leaflet map.
const SKY_LEAFLET_JS='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
const SKY_LEAFLET_CSS='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
let skyLeafletPromise;
function skyLoadLeaflet(){
  if(window.L) return Promise.resolve(window.L);
  if(!skyLeafletPromise) skyLeafletPromise=new Promise((resolve,reject)=>{
    const s=document.createElement('script');s.src=SKY_LEAFLET_JS;
    s.onload=()=>window.L?resolve(window.L):reject(new Error('Leaflet missing'));
    s.onerror=()=>reject(new Error('Leaflet could not load'));document.head.append(s);
  });
  return skyLeafletPromise;
}
class SkyLedgerMapCard extends HTMLElement {
  setConfig(config){this._config=config||{};}
  set hass(hass){this._hass=hass;if(this.isConnected)this.refresh();}
  connectedCallback(){
    if(this._connected)return;this._connected=true;
    if(!this.shadowRoot)this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML=`<link rel="stylesheet" href="${SKY_LEAFLET_CSS}"><style>
      :host{display:block;min-width:0}ha-card{display:block;overflow:hidden;border-radius:var(--ha-card-border-radius,12px)}
      .details{padding:16px 16px 10px;color:var(--primary-text-color)}
      .top{display:flex;justify-content:space-between;align-items:center;gap:12px}
      .route{font-size:21px;font-weight:650;line-height:1.3}
      .status{font-size:12px;font-weight:600;color:var(--success-color,#2e8b57)}
      .sub{font-size:13px;color:var(--secondary-text-color);margin-top:5px}
      .metrics{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:15px}
      .label{font-size:12px;color:var(--secondary-text-color);margin-bottom:3px}
      .value{font-size:15px;font-weight:600}
      .footer{font-size:12px;color:var(--secondary-text-color);margin-top:12px}
      #map{height:280px;width:100%;background:var(--secondary-background-color,#e7e7e7)}
      #notice{font-size:12px;padding:7px 14px;color:var(--secondary-text-color)}
      .leaflet-container{font-family:inherit}
    </style><ha-card><div class="details"><div class="top"><div class="route" id="route">Active flight</div><div class="status" id="status">AIRBORNE</div></div><div class="sub" id="aircraft"></div><div class="metrics"><div><div class="label">Takeoff</div><div class="value" id="takeoff">—</div></div><div><div class="label">Arrival</div><div class="value" id="arrival">—</div></div><div><div class="label">Altitude</div><div class="value" id="altitude">—</div></div><div><div class="label">Ground speed</div><div class="value" id="speed">—</div></div></div><div class="footer" id="travelers"></div></div><div id="map"></div><div id="notice">Loading map…</div></ha-card>`;
    skyLoadLeaflet().then(L=>{
      if(!this.isConnected)return;
      this._map=L.map(this.shadowRoot.getElementById('map'),{zoomControl:true}).setView([39,-96],4);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}).addTo(this._map);
      this.refresh();
      requestAnimationFrame(()=>this._map?.invalidateSize());
    }).catch(e=>{this._text('notice','Map unavailable: '+e.message);});
    this.refresh();
  }
  disconnectedCallback(){this._map?.remove();this._map=null;this._marker=null;this._trail=null;this._connected=false;}
  _text(id,value){const el=this.shadowRoot?.getElementById(id);if(el)el.textContent=value;}
  _time(value){if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat(undefined,{hour:'numeric',minute:'2-digit',timeZone:'America/New_York',timeZoneName:'short'}).format(d);}
  refresh(){
    if(!this.shadowRoot||!this._hass)return;
    const states=this._hass.states;
    const active=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.flight_')&&s.attributes?.flight_number&&String(s.state).toLowerCase()==='airborne');
    const f=active[0];if(!f)return;
    const m=f.attributes.metadata||{},ac=f.attributes.aircraft||{};
    const tracked=states['sensor.flightradar24_additional_tracked']?.attributes?.flights||[];
    const live=tracked.find(t=>t.flight_number===f.attributes.flight_number&&t.tracked_type==='live');
    this._text('route',`${f.attributes.flight_number} · ${m.departure_airport||'—'} → ${m.arrival_airport||'—'}`);
    this._text('aircraft',[ac.model,ac.registration].filter(Boolean).join(' · '));
    this._text('takeoff',this._time(f.attributes.actual_departure_utc||f.attributes.departed_at));
    this._text('arrival',this._time(m.revised_arrival_utc||f.attributes.scheduled_arrival_utc));
    this._text('altitude',Number.isFinite(Number(live?.altitude))?Math.round(Number(live.altitude)).toLocaleString()+' ft':'—');
    this._text('speed',Number.isFinite(Number(live?.ground_speed))?Math.round(Number(live.ground_speed))+' kt':'—');
    this._text('travelers','Travelers: '+(f.attributes.travelers||[]).map(id=>states[id]?.attributes?.friendly_name||id).join(', '));
    if(!this._map)return;
    const lat=Number(live?.latitude),lon=Number(live?.longitude);
    if(!live||!Number.isFinite(lat)||!Number.isFinite(lon)){
      this._text('notice','Aircraft position unavailable');
      if(this._marker){this._map.removeLayer(this._marker);this._marker=null;}
      if(this._trail){this._map.removeLayer(this._trail);this._trail=null;}
      return;
    }
    const L=window.L,pos=[lat,lon];
    // Circle marker avoids Leaflet default icon assets being blocked by HA shadow DOM.
    if(!this._marker)this._marker=L.circleMarker(pos,{radius:9,color:'#fff',weight:2,fillColor:'#157bd2',fillOpacity:1}).addTo(this._map);
    else this._marker.setLatLng(pos);
    this._marker.bindPopup(f.attributes.flight_number);
    const points=(live.coordinates||[]).filter(p=>Array.isArray(p)&&p.length>=2&&p.slice(0,2).every(n=>Number.isFinite(Number(n)))).map(p=>[Number(p[0]),Number(p[1])]);
    if(this._trail)this._map.removeLayer(this._trail);
    if(points.length>1)this._trail=L.polyline(points,{color:'#157bd2',weight:3}).addTo(this._map);
    if(this._flight!==f.attributes.id){this._flight=f.attributes.id;this._map.setView(pos,6);}
    else if(!this._last||this._last[0]!==lat||this._last[1]!==lon)this._map.panTo(pos);
    this._last=pos;this._text('notice','Live aircraft position · OpenStreetMap');
    requestAnimationFrame(()=>this._map?.invalidateSize());
  }
  getCardSize(){return 8;}
}
if(!customElements.get('skyledger-map-card'))customElements.define('skyledger-map-card',SkyLedgerMapCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==='skyledger-map-card'))window.customCards.push({type:'skyledger-map-card',name:'SkyLedger Active Flight',description:'Live flight details and OpenStreetMap'});
