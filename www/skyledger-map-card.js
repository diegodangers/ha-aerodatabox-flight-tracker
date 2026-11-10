// SkyLedger live aircraft map card. Reads existing Home Assistant FR24 sensor only.
const LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
let leafletReady;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletReady) {
    leafletReady = new Promise((resolve, reject) => {
      if (!document.querySelector('link[data-sky-leaflet]')) {
        const css=document.createElement('link'); css.rel='stylesheet'; css.href=LEAFLET_CSS; css.dataset.skyLeaflet='1'; document.head.append(css);
      }
      const script=document.createElement('script'); script.src=LEAFLET_JS;
      script.onload=()=>resolve(window.L); script.onerror=()=>reject(new Error('Leaflet failed to load'));
      document.head.append(script);
    });
  }
  return leafletReady;
}
class SkyLedgerMapCard extends HTMLElement {
  setConfig(config) { this.config=config; }
  set hass(hass) {
    this._hass=hass;
    if (!this.isConnected) return;
    this.refresh();
  }
  connectedCallback() {
    if (this._ready) return;
    this._ready=true;
    this.innerHTML='<ha-card><div id="skyledger-map" style="height:280px;width:100%;border-radius:12px;overflow:hidden"></div><div id="skyledger-status" style="padding:8px 12px;font-size:12px"></div></ha-card>';
    loadLeaflet().then(L=>{
      if (!this.isConnected) return;
      this._map=L.map(this.querySelector('#skyledger-map'),{zoomControl:true}).setView([39,-96],4);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}).addTo(this._map);
      this.refresh(); setTimeout(()=>this._map?.invalidateSize(),100);
    }).catch(()=>{this.querySelector('#skyledger-status').textContent='Map tiles unavailable';});
  }
  disconnectedCallback() { this._map?.remove(); this._map=null; this._ready=false; }
  refresh() {
    if (!this._map || !this._hass) return;
    const states=this._hass.states;
    const active=Object.values(states).filter(s=>s.entity_id.startsWith('sensor.flight_') && s.attributes.flight_number && s.state.toLowerCase()==='airborne');
    const flights=states['sensor.flightradar24_additional_tracked']?.attributes?.flights || [];
    const current=active.map(s=>flights.find(f=>f.flight_number===s.attributes.flight_number && f.tracked_type==='live')).find(f=>f && Number.isFinite(Number(f.latitude)) && Number.isFinite(Number(f.longitude)));
    const status=this.querySelector('#skyledger-status');
    if (!current) { if(this._marker){this._map.removeLayer(this._marker);this._marker=null;} if(this._trail){this._map.removeLayer(this._trail);this._trail=null;} status.textContent='Aircraft position unavailable'; return; }
    const L=window.L, lat=Number(current.latitude), lon=Number(current.longitude);
    const position=[lat,lon];
    if (!this._marker) this._marker=L.marker(position).addTo(this._map);
    else this._marker.setLatLng(position);
    this._marker.bindPopup(current.flight_number || 'Active aircraft');
    const points=(current.coordinates||[]).filter(p=>Array.isArray(p)&&p.length>=2&&Number.isFinite(Number(p[0]))&&Number.isFinite(Number(p[1]))).map(p=>[Number(p[0]),Number(p[1])]);
    if(this._trail) this._map.removeLayer(this._trail);
    if(points.length>1) this._trail=L.polyline(points,{color:'#2789ca',weight:3}).addTo(this._map);
    const key=current.flight_number;
    if(this._flight!==key){this._flight=key;this._map.setView(position,6);} else if(this._lastPosition && (this._lastPosition[0]!==lat || this._lastPosition[1]!==lon)) this._map.panTo(position);
    this._lastPosition=position;
    status.textContent=(current.flight_number||'Flight')+' · '+(current.altitude??'—')+' ft · '+(current.ground_speed??'—')+' kt';
  }
  getCardSize(){return 5;}
}
if (!customElements.get('skyledger-map-card')) customElements.define('skyledger-map-card',SkyLedgerMapCard);
window.customCards=window.customCards||[];
if (!window.customCards.some(c=>c.type==='skyledger-map-card')) window.customCards.push({type:'skyledger-map-card',name:'SkyLedger Aircraft Map',description:'OpenStreetMap map of the active flight'});
