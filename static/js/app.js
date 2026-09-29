/**
 * MPLADS Monitoring & Transparency Platform - Dynamic Frontend Application Script
 * 100% Data-Driven: Zero Hardcoded Numbers, Project Records, or Datasets.
 */

// Global State
let currentRole = "citizen";
let currentView = "landing";
let worksPage = 1;
let worksLimit = 20;
let worksScope = "all";
let analyticsData = null;
let geoMetadata = null;
let activeSelectedMp = "";
let activeSelectedDistrict = "";
let stateChartInstance = null;
let statusChartInstance = null;

// Currency Formatter
function formatINR(amount) {
  if (amount === undefined || amount === null || isNaN(amount)) return "₹0";
  const val = Number(amount);
  if (val >= 10000000) {
    return `₹${(val / 10000000).toFixed(2)} Cr`;
  } else if (val >= 100000) {
    return `₹${(val / 100000).toFixed(2)} Lakh`;
  }
  return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

// Format Date
function formatDate(dtStr) {
  if (!dtStr) return "N/A";
  try {
    const d = new Date(dtStr);
    if (isNaN(d.getTime())) return dtStr;
    return d.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
  } catch (e) {
    return dtStr;
  }
}

// Status Badges
function renderStatusBadge(status) {
  if (!status) return `<span class="badge-status bg-slate-100 text-slate-600">Pending</span>`;
  const s = status.toUpperCase();
  if (s.includes("COMPLETED")) {
    return `<span class="badge-status badge-completed">✓ Completed</span>`;
  } else if (s.includes("RECOMMENDED")) {
    return `<span class="badge-status badge-recommended">⏳ Recommended</span>`;
  } else if (s.includes("APPROVED") || s.includes("SANCTION")) {
    return `<span class="badge-status badge-approved">⚖️ Sanctioned</span>`;
  } else if (s.includes("PROGRESS") || s.includes("PHYSICAL") || s.includes("VENDOR")) {
    return `<span class="badge-status badge-in_progress">⚙️ In Progress</span>`;
  } else if (s.includes("RETURN") || s.includes("REJECT")) {
    return `<span class="badge-status badge-returned">↩ Returned</span>`;
  }
  return `<span class="badge-status bg-slate-100 text-slate-700">${status}</span>`;
}

// Navigation Handler across all 6 main tabs
function switchNav(viewName) {
  currentView = viewName;

  const views = ["landing", "citizen", "mp", "da", "ia", "analytics"];
  views.forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.classList.add("hidden");

    const navBtn = document.getElementById(`nav-${v}`);
    if (navBtn) {
      navBtn.classList.remove("bg-gov-primary", "text-white", "font-bold", "shadow-xs");
      navBtn.classList.add("text-slate-600", "hover:text-gov-primary", "hover:bg-slate-100");
    }
  });

  const activeEl = document.getElementById(`view-${viewName}`);
  if (activeEl) activeEl.classList.remove("hidden");

  const activeNavBtn = document.getElementById(`nav-${viewName}`);
  if (activeNavBtn) {
    activeNavBtn.classList.add("bg-gov-primary", "text-white", "font-bold", "shadow-xs");
    activeNavBtn.classList.remove("text-slate-600", "hover:text-gov-primary", "hover:bg-slate-100");
  }

  if (viewName === "citizen") {
    fetchWorks(worksPage);
  } else if (viewName === "mp") {
    loadMpDashboard(activeSelectedMp);
  } else if (viewName === "da") {
    const stateVal = document.getElementById("da-state-selector") ? document.getElementById("da-state-selector").value : "";
    const distVal = document.getElementById("da-district-selector") ? document.getElementById("da-district-selector").value : "";
    loadDaDashboard(stateVal, distVal);
  } else if (viewName === "ia") {
    loadIaDashboard();
  } else if (viewName === "analytics") {
    renderAnalyticsCharts();
  }
}

// Role Switcher Handler
function handleRoleChange(role) {
  currentRole = role;
  const labelEl = document.getElementById("current-user-label");

  if (role === "citizen") {
    if (labelEl) labelEl.textContent = "Citizen / Public — Demo User";
  } else if (role === "mp") {
    if (labelEl) labelEl.textContent = `MP Portal — Demo User (${activeSelectedMp || 'Demo'})`;
  } else if (role === "district_authority") {
    if (labelEl) labelEl.textContent = `District Authority — Demo User (${activeSelectedDistrict || 'Demo'})`;
  } else if (role === "implementing_agency") {
    if (labelEl) labelEl.textContent = "Implementing Agency — Demo User";
  }

  openCurrentPortal();
}

function openCurrentPortal() {
  if (currentRole === "mp") {
    switchNav("mp");
  } else if (currentRole === "district_authority") {
    switchNav("da");
  } else if (currentRole === "implementing_agency") {
    switchNav("ia");
  } else {
    switchNav("citizen");
  }
}

function setRoleAndOpen(role) {
  const select = document.getElementById("role-switcher");
  if (select) select.value = role;
  handleRoleChange(role);
}

// Modal Handlers
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("hidden");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("hidden");
}


// --- METADATA & DYNAMIC DROPDOWNS ---
async function fetchMetadata() {
  try {
    const res = await fetch("/api/metadata/geography");
    geoMetadata = await res.json();

    // 1. Populate State filter in Public Explorer
    const stateFilter = document.getElementById("filter-state");
    if (stateFilter && geoMetadata.states) {
      stateFilter.innerHTML = `<option value="">All States (${geoMetadata.states.length})</option>` +
        geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
    }

    // 2. Populate District filter in Public Explorer
    populatePublicDistricts("");

    // 3. Populate Category filter in Public Explorer
    const catFilter = document.getElementById("filter-category");
    if (catFilter && geoMetadata.categories) {
      catFilter.innerHTML = `<option value="">All Categories (${geoMetadata.categories.length})</option>` +
        geoMetadata.categories.map(c => `<option value="${c}">${c}</option>`).join("");
    }

    // 4. Populate MP Selector in MP Portal
    const mpSelect = document.getElementById("mp-selector");
    if (mpSelect && geoMetadata.mps && geoMetadata.mps.length > 0) {
      mpSelect.innerHTML = geoMetadata.mps.map(m => 
        `<option value="${m.mp_name}">${m.mp_name} (${m.constituency}, ${m.state})</option>`
      ).join("");
      activeSelectedMp = geoMetadata.mps[0].mp_name;
    }

    // 5. Populate State Selector in DA Portal
    const daStateSelect = document.getElementById("da-state-selector");
    if (daStateSelect && geoMetadata.states) {
      daStateSelect.innerHTML = `<option value="">All States</option>` +
        geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
      daStateSelect.value = "Madhya Pradesh";
      onDaStateChange("Madhya Pradesh", "Agar-Malwa");
    }

    // 6. Populate MP Recommend Modal Dropdowns
    const recState = document.getElementById("rec-state");
    if (recState && geoMetadata.states) {
      recState.innerHTML = geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
      onRecommendStateChange(geoMetadata.states[0]);
    }

    const recCat = document.getElementById("rec-category");
    if (recCat && geoMetadata.categories) {
      recCat.innerHTML = geoMetadata.categories.map(c => `<option value="${c}">${c}</option>`).join("");
    }

    // 7. Populate Agency dropdown in DA Review Modal
    const revAgency = document.getElementById("rev-agency-select");
    if (revAgency && geoMetadata.agencies) {
      revAgency.innerHTML = geoMetadata.agencies.map(a => 
        `<option value="${a.id}|${a.agency_name}">${a.designation} - ${a.agency_name}</option>`
      ).join("");
    }

  } catch (err) {
    console.error("Failed to load metadata:", err);
  }
}

async function onDaStateChange(selectedState, targetDistrict = "") {
  const daDistrictSelect = document.getElementById("da-district-selector");
  if (!daDistrictSelect) return;

  try {
    const res = await fetch(`/api/metadata/districts?state=${encodeURIComponent(selectedState)}`);
    const data = await res.json();
    const districts = data.districts || [];

    daDistrictSelect.innerHTML = `<option value="">All Districts (${districts.length})</option>` +
      districts.map(d => `<option value="${d}">${d}</option>`).join("");

    if (targetDistrict && districts.includes(targetDistrict)) {
      daDistrictSelect.value = targetDistrict;
    } else if (!targetDistrict && selectedState === "Madhya Pradesh" && districts.includes("Agar-Malwa")) {
      daDistrictSelect.value = "Agar-Malwa";
    }

    const currentDistrict = daDistrictSelect.value;
    activeSelectedDistrict = currentDistrict;
    loadDaDashboard(selectedState, currentDistrict);
  } catch (err) {
    console.error("Failed to load districts for DA portal:", err);
  }
}

function onDaDistrictChange(selectedDistrict) {
  const stateSelect = document.getElementById("da-state-selector");
  const selectedState = stateSelect ? stateSelect.value : "";
  activeSelectedDistrict = selectedDistrict;
  loadDaDashboard(selectedState, selectedDistrict);
}

function populatePublicDistricts(selectedState) {
  const distSelect = document.getElementById("filter-district");
  if (!distSelect || !geoMetadata || !geoMetadata.districts) return;

  let districts = geoMetadata.districts;
  if (selectedState && selectedState.trim() !== "" && !selectedState.toLowerCase().startsWith("all")) {
    districts = districts.filter(d => d.state === selectedState);
  }

  distSelect.innerHTML = `<option value="">All Districts (${districts.length})</option>` +
    districts.map(d => `<option value="${d.district}">${d.district}</option>`).join("");
}

function onStateFilterChange(selectedState) {
  populatePublicDistricts(selectedState);
  applyWorksFilter();
}

function resetPublicFilters() {
  if (document.getElementById("filter-q")) document.getElementById("filter-q").value = "";
  if (document.getElementById("filter-state")) document.getElementById("filter-state").value = "";
  if (document.getElementById("filter-district")) document.getElementById("filter-district").value = "";
  if (document.getElementById("filter-category")) document.getElementById("filter-category").value = "";
  if (document.getElementById("filter-status")) document.getElementById("filter-status").value = "";
  populatePublicDistricts("");
  fetchWorks(1);
}

function onRecommendStateChange(selectedState) {
  if (!geoMetadata) return;

  const stateDistricts = geoMetadata.districts.filter(d => d.state === selectedState);
  const districtSelect = document.getElementById("rec-district");
  if (districtSelect) {
    districtSelect.innerHTML = stateDistricts.map(d => `<option value="${d.district}">${d.district}</option>`).join("");
    if (stateDistricts.length > 0) {
      onRecommendDistrictChange(stateDistricts[0].district);
    }
  }
}

function onRecommendDistrictChange(selectedDistrict) {
  if (!geoMetadata) return;

  const stateSelect = document.getElementById("rec-state");
  const selectedState = stateSelect ? stateSelect.value : "";

  const districtConstituencies = geoMetadata.constituencies.filter(c => 
    c.district === selectedDistrict || (selectedState && c.state === selectedState)
  );

  const constSelect = document.getElementById("rec-constituency");
  if (constSelect) {
    if (districtConstituencies.length > 0) {
      constSelect.innerHTML = districtConstituencies.map(c => `<option value="${c.constituency}">${c.constituency}</option>`).join("");
    } else {
      constSelect.innerHTML = `<option value="${selectedDistrict} Constituency">${selectedDistrict} Constituency</option>`;
    }
  }
}

function changeActiveMp(mpName) {
  activeSelectedMp = mpName;
  const labelEl = document.getElementById("current-user-label");
  if (currentRole === "mp" && labelEl) {
    labelEl.textContent = `MP Portal — Demo User (${activeSelectedMp})`;
  }
  loadMpDashboard(activeSelectedMp);
}

function changeActiveDistrict(districtName) {
  const stateSelect = document.getElementById("da-state-selector");
  const selectedState = stateSelect ? stateSelect.value : "";
  onDaDistrictChange(districtName);
}


// --- 1. FETCH ANALYTICS OVERVIEW & DATA COVERAGE ---
async function fetchAnalyticsOverview() {
  try {
    const res = await fetch("/api/analytics/overview");
    analyticsData = await res.json();

    const k = analyticsData.kpis;

    // Landing KPIs
    document.getElementById("kpi-total-works").textContent = k.total_works.toLocaleString();
    document.getElementById("kpi-states-sub").textContent = `${analyticsData.state_breakdown.length} States & UTs Tracked`;

    document.getElementById("kpi-total-sanction").textContent = formatINR(k.total_sanction_amount);
    const meanOutlay = k.total_works > 0 ? (k.total_sanction_amount / k.total_works) : 0;
    document.getElementById("kpi-mean-outlay-sub").textContent = `Calculated Mean: ${formatINR(meanOutlay)} / work`;

    document.getElementById("kpi-total-disbursed").textContent = formatINR(k.total_disbursed_amount);
    document.getElementById("kpi-events-sub").textContent = `Calculated from ${k.total_payment_events.toLocaleString()} payment events`;

    document.getElementById("kpi-completion-rate").textContent = `${k.completion_rate_pct}%`;
    document.getElementById("kpi-completion-sub").textContent = `${k.completed_works.toLocaleString()} completed • ${k.ongoing_works.toLocaleString()} ongoing`;

    // Dynamic banner text
    const bannerInfo = document.getElementById("banner-dataset-info");
    if (bannerInfo) {
      bannerInfo.textContent = `${k.total_works.toLocaleString()} Projects & ${k.total_payment_events.toLocaleString()} Payment Events loaded from real CSV datasets.`;
    }

    // Connected System Datasets Coverage Component
    if (document.getElementById("coverage-projects-count")) {
      document.getElementById("coverage-projects-count").textContent = k.total_works.toLocaleString();
      document.getElementById("coverage-payments-count").textContent = k.total_payment_events.toLocaleString();
      document.getElementById("coverage-states-count").textContent = `${analyticsData.state_breakdown.length} States & UTs`;
      document.getElementById("coverage-live-count").textContent = `${k.live_works_count} Works`;
    }
  } catch (err) {
    console.error("Failed to load analytics overview:", err);
  }
}


// --- 2. PUBLIC EXPLORER (SEARCH & BROWSE) ---
async function fetchWorks(page = 1) {
  worksPage = page;
  const tbody = document.getElementById("works-table-body");
  tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-slate-400">Loading verified works from database...</td></tr>`;

  const q = document.getElementById("filter-q") ? document.getElementById("filter-q").value : "";
  const state = document.getElementById("filter-state") ? document.getElementById("filter-state").value : "";
  const district = document.getElementById("filter-district") ? document.getElementById("filter-district").value : "";
  const category = document.getElementById("filter-category") ? document.getElementById("filter-category").value : "";
  const status = document.getElementById("filter-status") ? document.getElementById("filter-status").value : "";

  const params = new URLSearchParams({
    page: worksPage,
    limit: worksLimit,
    scope: worksScope
  });
  if (q) params.append("q", q);
  if (state) params.append("state", state);
  if (district) params.append("district", district);
  if (category) params.append("category", category);
  if (status) params.append("status", status);

  try {
    const res = await fetch(`/api/works?${params.toString()}`);
    const data = await res.json();

    document.getElementById("works-count-label").textContent = data.total.toLocaleString();
    document.getElementById("current-page-num").textContent = data.page;
    document.getElementById("total-pages-num").textContent = data.total_pages || 1;

    document.getElementById("prev-page-btn").disabled = data.page <= 1;
    document.getElementById("next-page-btn").disabled = data.page >= data.total_pages;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-slate-500 font-medium">No matching works found. Try adjusting or clearing search filters.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.items.map(w => {
      const isLive = (w.source === "live");
      const sourceBadge = isLive 
        ? `<span class="bg-amber-100 text-amber-800 text-[10px] font-bold px-2 py-0.5 rounded border border-amber-200">LIVE APPLICATION RECORD</span>` 
        : `<span class="bg-slate-100 text-slate-600 text-[10px] font-semibold px-2 py-0.5 rounded border border-slate-200">HISTORICAL DATASET RECORD</span>`;

      return `
        <tr>
          <td>
            <div class="font-mono text-xs font-bold text-slate-800">${w.work_id}</div>
            <div class="flex items-center gap-1.5 mt-0.5">
              ${sourceBadge}
              <span class="text-[11px] text-slate-500">${w.work_category || 'General'}</span>
            </div>
          </td>
          <td>
            <div class="font-semibold text-slate-800 text-xs line-clamp-1" title="${w.work_title}">${w.work_title}</div>
            <div class="text-[11px] text-slate-500">${w.district}, ${w.state}</div>
          </td>
          <td>
            <div class="text-xs font-semibold text-gov-primary">${w.mp_name || 'MP'}</div>
            <div class="text-[11px] text-slate-500">${w.constituency}</div>
          </td>
          <td>
            <div class="font-semibold text-xs text-slate-800">${formatINR(w.sanction_amount)}</div>
            <div class="text-[11px] text-emerald-700 font-medium">Disbursed: ${formatINR(w.total_disbursed)}</div>
          </td>
          <td>
            <div class="flex items-center gap-2">
              <div class="w-16 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                <div class="bg-gov-primary h-1.5 rounded-full" style="width: ${w.physical_progress_pct || 0}%"></div>
              </div>
              <span class="text-[11px] font-bold text-slate-700">${w.physical_progress_pct || 0}%</span>
            </div>
          </td>
          <td>
            ${renderStatusBadge(w.status)}
          </td>
          <td>
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs font-bold text-gov-primary hover:text-blue-900 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1 rounded-md transition shadow-2xs">
              View Detail
            </button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.error("Error fetching works:", err);
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-red-500">Failed to load works from server: ${err.message}</td></tr>`;
  }
}

function applyWorksFilter() {
  fetchWorks(1);
}

function changeWorksPage(delta) {
  fetchWorks(worksPage + delta);
}

function setWorksScope(scope) {
  worksScope = scope;
  ["all", "live", "historical"].forEach(s => {
    const btn = document.getElementById(`scope-${s}`);
    if (btn) {
      if (s === scope) {
        btn.classList.add("bg-gov-primary", "text-white");
        btn.classList.remove("bg-slate-100", "text-slate-700");
      } else {
        btn.classList.remove("bg-gov-primary", "text-white");
        btn.classList.add("bg-slate-100", "text-slate-700");
      }
    }
  });
  fetchWorks(1);
}


// --- 3. WORK DETAIL MODAL ---
async function viewWorkDetail(workId) {
  try {
    const res = await fetch(`/api/works/${encodeURIComponent(workId)}`);
    if (!res.ok) throw new Error("No matching work found.");
    const data = await res.json();
    const w = data.work;

    document.getElementById("dtl-title").textContent = w.title;
    document.getElementById("dtl-wid").textContent = `ID: ${w.work_id}`;
    document.getElementById("dtl-badge").outerHTML = `<span id="dtl-badge">${renderStatusBadge(w.status)}</span>`;
    document.getElementById("dtl-source-tag").textContent = (w.source === 'live') ? 'LIVE APPLICATION RECORD' : 'HISTORICAL DATASET RECORD';

    document.getElementById("dtl-geo").textContent = `${w.district}, ${w.state}`;
    document.getElementById("dtl-constituency").textContent = w.constituency;
    document.getElementById("dtl-mp").textContent = w.mp_name;
    document.getElementById("dtl-category").textContent = w.work_category;
    document.getElementById("dtl-sanction-date").textContent = formatDate(w.sanction_date);
    document.getElementById("dtl-completion-date").textContent = formatDate(w.completion_date);

    document.getElementById("dtl-pct-label").textContent = `${w.physical_progress_pct || 0}%`;
    document.getElementById("dtl-progress-bar").style.width = `${w.physical_progress_pct || 0}%`;

    document.getElementById("dtl-sanction-amt").textContent = formatINR(w.sanction_amount);
    document.getElementById("dtl-disbursed-amt").textContent = formatINR(w.total_disbursed);

    document.getElementById("dtl-desc").textContent = w.description || "Project recorded in official MPLADS registry.";

    // Render payment tranches
    const ptbody = document.getElementById("dtl-payments-tbody");
    const payments = data.payments || [];
    document.getElementById("dtl-pay-count").textContent = `${payments.length} payment tranche(s)`;

    if (payments.length === 0) {
      ptbody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-slate-400">No payment events recorded yet for this project.</td></tr>`;
    } else {
      ptbody.innerHTML = payments.map(p => `
        <tr>
          <td>${formatDate(p.expenditure_date)}</td>
          <td class="font-medium text-slate-800">${p.vendor_name_normalized || p.vendor_name_raw}</td>
          <td><span class="text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded">✓ ${p.payment_status}</span></td>
          <td class="font-bold text-slate-800">${formatINR(p.reported_fund_disbursed_amount)}</td>
        </tr>
      `).join("");
    }

    openModal("modal-detail");
  } catch (err) {
    alert("Lookup message: " + err.message);
  }
}


// --- 4. MP PORTAL ---
async function loadMpDashboard(mpName) {
  try {
    const url = mpName ? `/api/mp/dashboard?mp_name=${encodeURIComponent(mpName)}` : `/api/mp/dashboard`;
    const res = await fetch(url);
    const data = await res.json();

    activeSelectedMp = data.mp_name;
    document.getElementById("mp-header-name").textContent = `MP Portal — ${data.mp_name}`;
    document.getElementById("mp-constituency").textContent = data.constituency || "Constituency";
    document.getElementById("mp-state").textContent = data.state || "State";

    const k = data.kpis;
    document.getElementById("mp-kpi-total").textContent = k.total_recommended.toLocaleString();
    document.getElementById("mp-kpi-pending").textContent = `${k.pending_review} pending review`;
    document.getElementById("mp-kpi-sanction").textContent = formatINR(k.sanctioned_amount);
    document.getElementById("mp-kpi-disbursed").textContent = formatINR(k.total_disbursed);
    document.getElementById("mp-kpi-completed").textContent = k.completed_works.toLocaleString();
    document.getElementById("mp-kpi-ongoing").textContent = `${k.in_progress_works.toLocaleString()} ongoing`;

    // Render live recommended works
    const liveTbody = document.getElementById("mp-live-works-tbody");
    if (!data.live_works || data.live_works.length === 0) {
      liveTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400">No live recommendations submitted yet. Click "+ Recommend New Work" to submit a live proposal.</td></tr>`;
    } else {
      liveTbody.innerHTML = data.live_works.map(w => `
        <tr>
          <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
          <td>
            <div class="font-semibold text-slate-800 text-xs">${w.title}</div>
            <div class="text-[11px] text-slate-500">${w.work_category} • ${w.location || ''}</div>
          </td>
          <td>
            <div class="font-bold text-xs">${formatINR(w.sanction_amount > 0 ? w.sanction_amount : w.estimated_amount)}</div>
            <div class="text-[10px] text-slate-500">${w.sanction_amount > 0 ? 'Sanctioned' : 'Est. Outlay'}</div>
          </td>
          <td>${renderStatusBadge(w.status)}</td>
          <td>
            <div class="flex items-center gap-1.5">
              <div class="w-12 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                <div class="bg-gov-primary h-1.5 rounded-full" style="width: ${w.physical_progress_pct || 0}%"></div>
              </div>
              <span class="text-xs font-bold">${w.physical_progress_pct || 0}%</span>
            </div>
          </td>
          <td class="text-xs text-slate-700 font-medium">${w.assigned_agency_name || 'Pending Assignment'}</td>
          <td>
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs text-gov-primary font-bold hover:underline">
              Inspect
            </button>
          </td>
        </tr>
      `).join("");
    }

    // Render historical constituency works
    const histTbody = document.getElementById("mp-hist-works-tbody");
    if (data.recent_historical && data.recent_historical.length > 0) {
      histTbody.innerHTML = data.recent_historical.map(w => `
        <tr>
          <td class="font-mono text-xs font-bold">${w.work_id}</td>
          <td class="text-xs font-medium text-slate-800 line-clamp-1">${w.work_title}</td>
          <td class="text-xs text-slate-600">${formatDate(w.sanction_date)}</td>
          <td class="text-xs font-semibold text-slate-800">${formatINR(w.sanction_amount)}</td>
          <td class="text-xs font-semibold text-emerald-700">${formatINR(w.total_disbursed)}</td>
          <td>${renderStatusBadge(w.work_completion_status)}</td>
          <td>
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs text-gov-primary font-bold hover:underline">
              View
            </button>
          </td>
        </tr>
      `).join("");
    } else {
      histTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400">No historical records found for this MP.</td></tr>`;
    }
  } catch (err) {
    console.error("Failed to load MP dashboard:", err);
  }
}

function openRecommendModal() {
  openModal("modal-recommend");
}

async function submitRecommendation(e) {
  e.preventDefault();
  const payload = {
    title: document.getElementById("rec-title").value.trim(),
    work_category: document.getElementById("rec-category").value,
    priority: document.getElementById("rec-priority").value,
    state: document.getElementById("rec-state").value,
    district: document.getElementById("rec-district").value,
    constituency: document.getElementById("rec-constituency").value,
    location: document.getElementById("rec-location").value.trim(),
    estimated_amount: parseFloat(document.getElementById("rec-amount").value),
    beneficiary_purpose: document.getElementById("rec-purpose").value.trim(),
    recommending_mp_name: activeSelectedMp || "MP (Demo User)"
  };

  try {
    const res = await fetch("/api/mp/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "Failed to submit recommendation");

    alert(`✅ Live Recommendation Created!\nWork ID: ${result.work_id}\nStatus: ${result.status}\nSaved to application database.`);
    closeModal("modal-recommend");
    document.getElementById("form-recommend").reset();
    loadMpDashboard(activeSelectedMp);
    fetchAnalyticsOverview();
  } catch (err) {
    alert("Error submitting recommendation: " + err.message);
  }
}


// --- 5. DISTRICT AUTHORITY (DA) PORTAL ---
async function loadDaDashboard(stateName, districtName) {
  try {
    const params = new URLSearchParams();
    if (stateName) params.append("state", stateName);
    if (districtName) params.append("district", districtName);

    const res = await fetch(`/api/da/dashboard?${params.toString()}`);
    const data = await res.json();

    activeSelectedDistrict = data.district;
    document.getElementById("da-district-name").textContent = data.district || "All Districts";
    document.getElementById("da-state-name").textContent = data.state || "All States";
    if (document.getElementById("da-district-sub")) {
      document.getElementById("da-district-sub").textContent = `${data.district}, ${data.state}`;
    }

    const k = data.kpis;
    document.getElementById("da-kpi-total").textContent = (k.historical_district_works + k.active_live_works).toLocaleString();
    document.getElementById("da-kpi-sanction").textContent = formatINR(k.district_sanction_amount);
    document.getElementById("da-kpi-disbursed").textContent = formatINR(k.district_disbursed_amount);
    document.getElementById("da-kpi-completed").textContent = k.district_completed.toLocaleString();
    document.getElementById("da-kpi-ongoing").textContent = `${k.district_ongoing.toLocaleString()} ongoing`;

    // Section A: Pending MP Recommendations
    document.getElementById("da-pending-badge").textContent = data.pending_recommendations.length;
    const pendingTbody = document.getElementById("da-pending-tbody");
    if (!data.pending_recommendations || data.pending_recommendations.length === 0) {
      pendingTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400 font-medium">No pending recommendations currently in queue for ${data.district}.</td></tr>`;
    } else {
      pendingTbody.innerHTML = data.pending_recommendations.map(w => `
        <tr class="bg-amber-50/40">
          <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
          <td class="text-xs font-semibold text-gov-primary">${w.recommending_mp_name}</td>
          <td>
            <div class="font-semibold text-xs text-slate-800">${w.title}</div>
            <div class="text-[11px] text-slate-500">${w.beneficiary_purpose || ''}</div>
          </td>
          <td class="font-bold text-xs text-emerald-800">${formatINR(w.estimated_amount)}</td>
          <td class="text-xs text-slate-600">${formatDate(w.recommended_date)}</td>
          <td>${renderStatusBadge(w.status)}</td>
          <td>
            <button onclick="openReviewModal('${w.work_id}', '${escape(w.title)}', ${w.estimated_amount})" class="bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold px-3 py-1.5 rounded-lg shadow-2xs transition">
              Review & Sanction
            </button>
          </td>
        </tr>
      `).join("");
    }

    // Section B: Existing Works in Selected District (Combines active live works + real historical district works)
    const activeTbody = document.getElementById("da-active-tbody");
    const combinedWorks = [
      ...(data.active_live_works || []).map(w => ({ ...w, is_live: true })),
      ...(data.historical_district_works || []).map(w => ({
        work_id: w.work_id,
        title: w.work_title,
        work_category: w.work_category,
        mp_name: w.mp_name,
        constituency: w.constituency,
        sanction_amount: w.sanction_amount,
        total_disbursed: w.total_disbursed,
        status: w.status,
        is_live: false
      }))
    ];

    if (combinedWorks.length === 0) {
      activeTbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400 font-medium">No historical works found for this district in the connected dataset.</td></tr>`;
    } else {
      activeTbody.innerHTML = combinedWorks.map(w => `
        <tr>
          <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
          <td>
            <div class="text-xs font-semibold text-slate-800 line-clamp-1" title="${w.title}">${w.title}</div>
            <div class="text-[11px] text-slate-500">${w.work_category || 'General'}</div>
          </td>
          <td>
            <div class="text-xs font-semibold text-gov-primary">${w.mp_name || 'MP'}</div>
            <div class="text-[11px] text-slate-500">${w.constituency || ''}</div>
          </td>
          <td class="text-xs font-bold text-slate-800">${formatINR(w.sanction_amount)}</td>
          <td class="text-xs font-semibold text-emerald-700">${formatINR(w.total_disbursed)}</td>
          <td>${renderStatusBadge(w.status)}</td>
          <td>
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs text-gov-primary font-bold hover:underline">
              Inspect
            </button>
          </td>
        </tr>
      `).join("");
    }
  } catch (err) {
    console.error("Failed to load DA dashboard:", err);
  }
}

function openReviewModal(workId, titleEscaped, estimatedAmount) {
  document.getElementById("rev-hidden-work-id").value = workId;
  document.getElementById("rev-work-id").textContent = workId;
  document.getElementById("rev-work-title").textContent = unescape(titleEscaped);
  document.getElementById("rev-proposed-outlay").textContent = formatINR(estimatedAmount);
  document.getElementById("rev-sanction-amount").value = estimatedAmount;
  openModal("modal-review");
}

function toggleReviewAction(action) {
  const fields = document.getElementById("approve-fields");
  const submitBtn = document.getElementById("rev-submit-btn");
  if (action === "RETURN") {
    fields.classList.add("hidden");
    submitBtn.textContent = "Return to MP with Remarks";
    submitBtn.className = "px-5 py-2 bg-red-700 hover:bg-red-800 text-white rounded-lg font-semibold shadow-xs";
  } else {
    fields.classList.remove("hidden");
    submitBtn.textContent = "Confirm & Issue Sanction Order";
    submitBtn.className = "px-5 py-2 bg-emerald-700 hover:bg-emerald-800 text-white rounded-lg font-semibold shadow-xs";
  }
}

async function submitReview(e) {
  e.preventDefault();
  const workId = document.getElementById("rev-hidden-work-id").value;
  const actionRadio = document.querySelector('input[name="rev_action"]:checked');
  const action = actionRadio ? actionRadio.value : "APPROVE";
  const agencySelect = document.getElementById("rev-agency-select").value.split("|");

  const payload = {
    work_id: workId,
    action: action,
    sanction_amount: parseFloat(document.getElementById("rev-sanction-amount").value),
    assigned_agency_id: parseInt(agencySelect[0]) || 1,
    assigned_agency_name: agencySelect[1] || "Assigned Agency",
    review_comments: document.getElementById("rev-comments").value.trim()
  };

  try {
    const res = await fetch("/api/da/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "Review failed");

    alert(`✅ Action Recorded!\nWork ID: ${result.work_id}\nNew Status: ${result.new_status}`);
    closeModal("modal-review");
    const stateVal = document.getElementById("da-state-selector") ? document.getElementById("da-state-selector").value : "";
    loadDaDashboard(stateVal, activeSelectedDistrict);
    fetchAnalyticsOverview();
  } catch (err) {
    alert("Error recording review: " + err.message);
  }
}


// --- 6. IMPLEMENTING AGENCY (IA) PORTAL ---
async function loadIaDashboard() {
  try {
    const res = await fetch("/api/agency/dashboard");
    const data = await res.json();

    document.getElementById("ia-assigned-count").textContent = `${data.kpis.total_assigned} Works`;

    const tbody = document.getElementById("ia-assigned-tbody");
    if (!data.assigned_works || data.assigned_works.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-400 font-medium">No approved live works assigned yet. Works will appear here once approved by District Authority.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.assigned_works.map(w => `
      <tr>
        <td class="font-mono text-xs font-bold text-slate-800">${w.work_id}</td>
        <td>
          <div class="font-semibold text-slate-800 text-xs">${w.title}</div>
          <div class="text-[11px] text-slate-500">${w.work_category} • Milestone: ${w.current_milestone || 'Planning'}</div>
        </td>
        <td class="font-bold text-xs text-slate-800">${formatINR(w.sanction_amount)}</td>
        <td class="font-semibold text-xs text-emerald-700">${formatINR(w.total_disbursed)}</td>
        <td>
          <div class="flex items-center gap-1.5">
            <div class="w-16 bg-slate-200 rounded-full h-1.5 overflow-hidden">
              <div class="bg-gov-primary h-1.5 rounded-full" style="width: ${w.physical_progress_pct || 0}%"></div>
            </div>
            <span class="text-xs font-bold text-slate-700">${w.physical_progress_pct || 0}%</span>
          </div>
        </td>
        <td>${renderStatusBadge(w.status)}</td>
        <td>
          <button onclick="openProgressModal('${w.work_id}', '${escape(w.title)}', ${w.physical_progress_pct || 0})" class="bg-gov-primary hover:bg-blue-800 text-white text-xs font-bold px-3 py-1.5 rounded-lg shadow-2xs transition">
            Update Progress
          </button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Failed to load Agency dashboard:", err);
  }
}

function openProgressModal(workId, titleEscaped, currentPct) {
  document.getElementById("prog-hidden-wid").value = workId;
  document.getElementById("prog-modal-wid").textContent = workId;
  document.getElementById("prog-modal-title").textContent = unescape(titleEscaped);
  document.getElementById("prog-range").value = currentPct;
  document.getElementById("prog-pct-num").value = currentPct;
  openModal("modal-progress");
}

async function submitProgressUpdate(e) {
  e.preventDefault();
  const workId = document.getElementById("prog-hidden-wid").value;
  const pct = parseInt(document.getElementById("prog-pct-num").value);
  const status = document.getElementById("prog-status").value;
  const milestone = document.getElementById("prog-milestone").value;
  const expenditure = parseFloat(document.getElementById("prog-expenditure").value) || 0.0;
  const desc = document.getElementById("prog-desc").value.trim();
  const voucher = document.getElementById("prog-voucher").value.trim();

  const payload = {
    work_id: workId,
    physical_progress_pct: pct,
    status: status,
    current_milestone: milestone,
    description: desc,
    expenditure_incurred: expenditure,
    payment_notes: voucher
  };

  try {
    const res = await fetch("/api/agency/update-progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || "Failed to update progress");

    alert(`✅ Progress Recorded!\nWork ID: ${result.work_id}\nPhysical Progress: ${result.physical_progress_pct}%\nStatus: ${result.status}`);
    closeModal("modal-progress");
    loadIaDashboard();
    fetchAnalyticsOverview();
  } catch (err) {
    alert("Error updating progress: " + err.message);
  }
}


// --- 7. DYNAMIC ANALYTICS & CHARTS ---
function renderAnalyticsCharts() {
  if (!analyticsData) return;

  // 1. State-Wise Projects Bar Chart
  const stateCtx = document.getElementById("chart-states");
  if (stateCtx && analyticsData.state_breakdown) {
    const states = analyticsData.state_breakdown;
    const labels = states.map(s => s.state);
    const counts = states.map(s => s.project_count);

    if (stateChartInstance) stateChartInstance.destroy();
    stateChartInstance = new Chart(stateCtx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: "Number of Projects",
          data: counts,
          backgroundColor: "#0F4C81",
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          y: { beginAtZero: true, grid: { color: "#F1F5F9" } },
          x: { grid: { display: false } }
        }
      }
    });
  }

  // 2. Execution Status Doughnut Chart
  const statusCtx = document.getElementById("chart-status");
  if (statusCtx && analyticsData.status_breakdown) {
    const statuses = analyticsData.status_breakdown;
    const labels = statuses.map(s => s.status);
    const counts = statuses.map(s => s.count);

    if (statusChartInstance) statusChartInstance.destroy();
    statusChartInstance = new Chart(statusCtx, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{
          data: counts,
          backgroundColor: ["#0A2540", "#0F4C81", "#2563EB", "#38BDF8", "#107C41", "#F58220", "#64748B"]
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12, font: { size: 10 } } }
        }
      }
    });
  }

  // 3. State Summary Table
  const tbody = document.getElementById("analytics-states-tbody");
  if (tbody && analyticsData.state_breakdown) {
    tbody.innerHTML = analyticsData.state_breakdown.map(s => {
      const completionRate = s.project_count > 0 ? ((s.completed_count / s.project_count) * 100).toFixed(1) : 0;
      return `
        <tr>
          <td class="font-bold text-slate-800">${s.state}</td>
          <td>${s.project_count.toLocaleString()}</td>
          <td class="font-semibold text-slate-800">${formatINR(s.total_sanction)}</td>
          <td class="font-semibold text-emerald-700">${formatINR(s.total_disbursed)}</td>
          <td>${s.completed_count.toLocaleString()}</td>
          <td>
            <div class="flex items-center gap-2">
              <span class="font-bold text-xs">${completionRate}%</span>
              <div class="w-12 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                <div class="bg-emerald-600 h-1.5 rounded-full" style="width: ${completionRate}%"></div>
              </div>
            </div>
          </td>
        </tr>
      `;
    }).join("");
  }
}

// Initial Boot
document.addEventListener("DOMContentLoaded", () => {
  fetchMetadata();
  fetchAnalyticsOverview();
  switchNav("landing");
  if (window.lucide) {
    window.lucide.createIcons();
  }
});
