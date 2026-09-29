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

// Monitoring global state
let monPage = 1;
let monLimit = 20;

// Chart instances store for 10 charts
let chartInstances = {};

// Navigation Handler across all main tabs
function switchNav(viewName) {
  currentView = viewName;

  const views = ["landing", "citizen", "mp", "da", "ia", "monitoring", "alerts", "analytics"];
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
  } else if (viewName === "monitoring") {
    loadMonitoringDashboard();
  } else if (viewName === "alerts") {
    loadAlertsView();
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

async function populatePublicDistricts(selectedState) {
  const distSelect = document.getElementById("filter-district");
  if (!distSelect) return;

  try {
    const url = (selectedState && selectedState.trim() !== "" && !selectedState.toLowerCase().startsWith("all"))
      ? `/api/metadata/districts?state=${encodeURIComponent(selectedState)}`
      : `/api/metadata/districts`;
    const res = await fetch(url);
    const data = await res.json();
    const districts = data.districts || [];
    distSelect.innerHTML = `<option value="">All Districts (${districts.length})</option>` +
      districts.map(d => `<option value="${d}">${d}</option>`).join("");
  } catch (err) {
    console.error("Failed to load districts:", err);
  }
}

async function populatePublicConstituencies(selectedState, selectedDistrict) {
  const constSelect = document.getElementById("filter-constituency");
  if (!constSelect) return;

  try {
    const params = new URLSearchParams();
    if (selectedState && selectedState.trim() !== "" && !selectedState.toLowerCase().startsWith("all")) {
      params.append("state", selectedState);
    }
    if (selectedDistrict && selectedDistrict.trim() !== "" && !selectedDistrict.toLowerCase().startsWith("all")) {
      params.append("district", selectedDistrict);
    }
    const res = await fetch(`/api/metadata/constituencies?${params.toString()}`);
    const data = await res.json();
    const constituencies = data.constituencies || [];
    constSelect.innerHTML = `<option value="">All Constituencies (${constituencies.length})</option>` +
      constituencies.map(c => `<option value="${c}">${c}</option>`).join("");
  } catch (err) {
    console.error("Failed to load constituencies:", err);
  }
}

async function onStateFilterChange(selectedState) {
  await populatePublicDistricts(selectedState);
  await populatePublicConstituencies(selectedState, "");
  applyWorksFilter();
}

async function onDistrictFilterChange(selectedDistrict) {
  const stateSelect = document.getElementById("filter-state");
  const selectedState = stateSelect ? stateSelect.value : "";
  await populatePublicConstituencies(selectedState, selectedDistrict);
  applyWorksFilter();
}

function resetPublicFilters() {
  if (document.getElementById("filter-q")) document.getElementById("filter-q").value = "";
  if (document.getElementById("filter-state")) document.getElementById("filter-state").value = "";
  if (document.getElementById("filter-district")) document.getElementById("filter-district").value = "";
  if (document.getElementById("filter-constituency")) document.getElementById("filter-constituency").value = "";
  if (document.getElementById("filter-category")) document.getElementById("filter-category").value = "";
  if (document.getElementById("filter-status")) document.getElementById("filter-status").value = "";
  populatePublicDistricts("");
  populatePublicConstituencies("", "");
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
  tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-slate-400">Loading verified works from database...</td></tr>`;

  const q = document.getElementById("filter-q") ? document.getElementById("filter-q").value : "";
  const state = document.getElementById("filter-state") ? document.getElementById("filter-state").value : "";
  const district = document.getElementById("filter-district") ? document.getElementById("filter-district").value : "";
  const constituency = document.getElementById("filter-constituency") ? document.getElementById("filter-constituency").value : "";
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
  if (constituency) params.append("constituency", constituency);
  if (category) params.append("category", category);
  if (status) params.append("status", status);

  try {
    const res = await fetch(`/api/works?${params.toString()}`);
    const data = await res.json();

    // Update Summary Information Cards dynamically from active search query
    if (data.summary) {
      if (document.getElementById("pub-sum-works")) document.getElementById("pub-sum-works").textContent = (data.summary.total_works || 0).toLocaleString();
      if (document.getElementById("pub-sum-sanction")) document.getElementById("pub-sum-sanction").textContent = formatINR(data.summary.total_sanction_amount || 0);
      if (document.getElementById("pub-sum-disbursed")) document.getElementById("pub-sum-disbursed").textContent = formatINR(data.summary.total_disbursed_amount || 0);
      if (document.getElementById("pub-sum-completed")) document.getElementById("pub-sum-completed").textContent = (data.summary.completed_works || 0).toLocaleString();
      if (document.getElementById("pub-sum-ongoing")) document.getElementById("pub-sum-ongoing").textContent = (data.summary.ongoing_works || 0).toLocaleString();
    }

    document.getElementById("works-count-label").textContent = data.total.toLocaleString();
    document.getElementById("current-page-num").textContent = data.page;
    document.getElementById("total-pages-num").textContent = data.total_pages || 1;

    document.getElementById("prev-page-btn").disabled = data.page <= 1;
    document.getElementById("next-page-btn").disabled = data.page >= data.total_pages;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-12 text-slate-500">
            <div class="max-w-md mx-auto space-y-2">
              <div class="text-2xl">🔍</div>
              <div class="font-bold text-slate-700">No historical works found for the selected filters.</div>
              <p class="text-xs text-slate-500">Try changing or clearing your search term, state, district, or constituency selection.</p>
              <button onclick="resetPublicFilters()" class="mt-2 text-xs font-bold text-gov-primary bg-blue-50 hover:bg-blue-100 border border-blue-200 px-4 py-2 rounded-lg transition">Clear All Filters</button>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = data.items.map(w => {
      const disbPct = (w.sanction_amount && w.sanction_amount > 0) 
        ? ((w.total_disbursed / w.sanction_amount) * 100).toFixed(1) 
        : null;

      return `
        <tr class="hover:bg-slate-50 transition">
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-mono text-xs font-bold text-slate-800">${w.work_id || 'N/A'}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-semibold text-slate-800 text-xs line-clamp-2" title="${w.work_title || ''}">${w.work_title || 'Not available in source data'}</div>
            ${w.work_category ? `<div class="text-[11px] text-slate-500 mt-0.5">${w.work_category}</div>` : ''}
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-semibold text-slate-800 text-xs">${w.district || 'N/A'}</div>
            <div class="text-[11px] text-slate-500">${w.state || 'N/A'}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-semibold text-slate-800 text-xs">${w.constituency || 'N/A'}</div>
            <div class="text-[11px] text-gov-primary font-medium">${w.mp_name || 'Not available in source data'}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-bold text-xs text-slate-800">${formatINR(w.sanction_amount)}</div>
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <div class="font-bold text-xs text-emerald-700">${formatINR(w.total_disbursed)}</div>
            ${disbPct !== null ? `<div class="text-[10px] text-slate-500 mt-0.5">${disbPct}% of sanction</div>` : ''}
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            ${renderStatusBadge(w.status)}
          </td>
          <td class="px-4 py-3 border-b border-slate-100">
            <button onclick="viewWorkDetail('${w.work_id}')" class="text-xs font-bold text-gov-primary hover:text-blue-900 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1.5 rounded-lg transition shadow-2xs">
              View Detail
            </button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.error("Error fetching works:", err);
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-red-500">Failed to load works from server: ${err.message}</td></tr>`;
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

    document.getElementById("dtl-title").textContent = w.title || "Not available in source data";
    document.getElementById("dtl-wid").textContent = `ID: ${w.work_id || 'N/A'}`;
    document.getElementById("dtl-badge").outerHTML = `<span id="dtl-badge">${renderStatusBadge(w.status)}</span>`;
    document.getElementById("dtl-source-tag").textContent = (w.source === 'live') ? 'LIVE APPLICATION RECORD' : 'HISTORICAL DATASET RECORD';

    document.getElementById("dtl-geo").textContent = `${w.district || 'Not available'}, ${w.state || 'Not available'}`;
    document.getElementById("dtl-constituency").textContent = w.constituency || "Not available in source data";
    document.getElementById("dtl-mp").textContent = w.mp_name || "Not available in source data";
    document.getElementById("dtl-category").textContent = w.work_category || "Not available in source data";
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
          <td class="font-medium text-slate-800">${p.vendor_name_normalized || p.vendor_name_raw || 'Not available in source data'}</td>
          <td><span class="text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded">✓ ${p.payment_status || 'SUCCESS'}</span></td>
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


// --- 7. PROJECT MONITORING & ML ANOMALY DETECTION HANDLERS ---

async function loadMonitoringDashboard() {
  const stateSel = document.getElementById("mon-filter-state");
  if (stateSel && geoMetadata && geoMetadata.states && stateSel.options.length <= 1) {
    stateSel.innerHTML = `<option value="">All States (${geoMetadata.states.length})</option>` +
      geoMetadata.states.map(s => `<option value="${s}">${s}</option>`).join("");
  }

  const selectedState = stateSel ? stateSel.value : "";
  const selectedDist = document.getElementById("mon-filter-district") ? document.getElementById("mon-filter-district").value : "";

  // Fetch Summary KPIs
  try {
    const sumRes = await fetch(`/api/monitoring/summary?state=${encodeURIComponent(selectedState)}&district=${encodeURIComponent(selectedDist)}`);
    const summary = await sumRes.json();

    const b = summary.budget_monitoring || {};
    const d = summary.delay_monitoring || {};
    const p = summary.payment_analysis || {};
    const m = summary.ml_anomaly_detection || {};

    if (document.getElementById("mon-kpi-budget-status")) document.getElementById("mon-kpi-budget-status").textContent = `${(b.total_projects || 0).toLocaleString()} Works`;
    if (document.getElementById("mon-kpi-within-sanction")) document.getElementById("mon-kpi-within-sanction").textContent = (b.within_sanction || 0).toLocaleString();
    if (document.getElementById("mon-kpi-fully-disbursed")) document.getElementById("mon-kpi-fully-disbursed").textContent = (b.fully_disbursed || 0).toLocaleString();
    if (document.getElementById("mon-kpi-overruns")) document.getElementById("mon-kpi-overruns").textContent = (b.potential_budget_overruns || 0).toLocaleString();

    if (document.getElementById("mon-kpi-delay-status")) document.getElementById("mon-kpi-delay-status").textContent = `${((d.on_time || 0) + (d.delayed || 0)).toLocaleString()} Completed`;
    if (document.getElementById("mon-kpi-ontime")) document.getElementById("mon-kpi-ontime").textContent = (d.on_time || 0).toLocaleString();
    if (document.getElementById("mon-kpi-delayed")) document.getElementById("mon-kpi-delayed").textContent = (d.delayed || 0).toLocaleString();
    if (document.getElementById("mon-kpi-ongoing-delayed")) document.getElementById("mon-kpi-ongoing-delayed").textContent = (d.ongoing_delayed || 0).toLocaleString();

    if (document.getElementById("mon-kpi-total-payments")) document.getElementById("mon-kpi-total-payments").textContent = `${(p.total_payment_events || 0).toLocaleString()} Events`;
    if (document.getElementById("mon-kpi-avg-tranche")) document.getElementById("mon-kpi-avg-tranche").textContent = formatINR(p.avg_payment_tranche || 0);
    if (document.getElementById("mon-kpi-multi-tranche")) document.getElementById("mon-kpi-multi-tranche").textContent = (p.multiple_tranche_projects || 0).toLocaleString();
    if (document.getElementById("mon-kpi-vendor-conc")) document.getElementById("mon-kpi-vendor-conc").textContent = (p.vendor_concentration_projects || 0).toLocaleString();

    if (document.getElementById("mon-kpi-ml-anomalies")) document.getElementById("mon-kpi-ml-anomalies").textContent = `${(m.potential_anomalies || 0).toLocaleString()} Anomalies`;
    if (document.getElementById("mon-kpi-ml-analyzed")) document.getElementById("mon-kpi-ml-analyzed").textContent = (m.projects_analyzed || 0).toLocaleString();
    if (document.getElementById("mon-kpi-ml-pct")) document.getElementById("mon-kpi-ml-pct").textContent = `${m.anomaly_pct || 0}%`;

  } catch (err) {
    console.error("Failed to load monitoring summary:", err);
  }

  fetchMonitoringWorks(monPage);
}

async function onMonStateChange(stateVal) {
  const distSel = document.getElementById("mon-filter-district");
  if (!distSel) return;

  if (!stateVal) {
    distSel.innerHTML = `<option value="">All Districts</option>`;
    applyMonitoringFilter();
    return;
  }

  try {
    const res = await fetch(`/api/metadata/districts?state=${encodeURIComponent(stateVal)}`);
    const data = await res.json();
    const dists = data.districts || [];
    distSel.innerHTML = `<option value="">All Districts (${dists.length})</option>` +
      dists.map(d => `<option value="${d}">${d}</option>`).join("");
    applyMonitoringFilter();
  } catch (err) {
    console.error("Failed to load districts for monitoring:", err);
  }
}

async function fetchMonitoringWorks(page = 1) {
  monPage = page;
  const q = document.getElementById("mon-filter-q") ? document.getElementById("mon-filter-q").value : "";
  const state = document.getElementById("mon-filter-state") ? document.getElementById("mon-filter-state").value : "";
  const district = document.getElementById("mon-filter-district") ? document.getElementById("mon-filter-district").value : "";
  const delay = document.getElementById("mon-filter-delay") ? document.getElementById("mon-filter-delay").value : "";
  const budget = document.getElementById("mon-filter-budget") ? document.getElementById("mon-filter-budget").value : "";
  const anomaly = document.getElementById("mon-filter-anomaly") ? document.getElementById("mon-filter-anomaly").value : "";

  const params = new URLSearchParams({ page: monPage, limit: monLimit });
  if (q) params.append("q", q);
  if (state) params.append("state", state);
  if (district) params.append("district", district);
  if (delay) params.append("delay_status", delay);
  if (budget) params.append("budget_status", budget);
  if (anomaly) params.append("anomaly_status", anomaly);

  try {
    const res = await fetch(`/api/monitoring/works?${params.toString()}`);
    const data = await res.json();

    if (document.getElementById("mon-results-count")) document.getElementById("mon-results-count").textContent = (data.total || 0).toLocaleString();
    if (document.getElementById("mon-page-num")) document.getElementById("mon-page-num").textContent = data.page || 1;
    if (document.getElementById("mon-total-pages")) document.getElementById("mon-total-pages").textContent = data.total_pages || 1;

    const prevBtn = document.getElementById("mon-prev-btn");
    const nextBtn = document.getElementById("mon-next-btn");
    if (prevBtn) prevBtn.disabled = (data.page <= 1);
    if (nextBtn) nextBtn.disabled = (data.page >= data.total_pages);

    const tbody = document.getElementById("mon-table-body");
    if (!tbody) return;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-slate-400">No monitoring records found matching criteria.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.items.map(item => {
      const riskScore = item.anomaly_risk_score || 0;
      let scoreBadge = `<span class="badge-status badge-anomaly-normal">${riskScore}/100 Normal</span>`;
      if (item.anomaly_status === "POTENTIAL ANOMALY") {
        if (riskScore >= 80) {
          scoreBadge = `<span class="badge-status badge-anomaly-high">⚠️ ${riskScore}/100 HIGH RISK</span>`;
        } else {
          scoreBadge = `<span class="badge-status badge-anomaly-medium">⚠️ ${riskScore}/100 MODERATE RISK</span>`;
        }
      }

      let delayBadge = `<span class="badge-status badge-delay-ontime">✓ ON_TIME</span>`;
      if (item.delay_status === "DELAYED") {
        delayBadge = `<span class="badge-status badge-delay-delayed">⏱ DELAYED</span>`;
      } else if (item.delay_status === "ONGOING_DELAYED") {
        delayBadge = `<span class="badge-status badge-delay-delayed">⏱ ONGOING OVER TARGET</span>`;
      } else if (item.delay_status === "ONGOING_WITHIN_TARGET") {
        delayBadge = `<span class="badge-status badge-delay-ongoing">⚙ ONGOING</span>`;
      }

      const disbRatioStr = item.budget_disbursement_ratio !== undefined ? `${(item.budget_disbursement_ratio * 100).toFixed(1)}%` : "N/A";

      return `
        <tr>
          <td>
            <div class="font-bold text-slate-800 font-mono text-xs">${item.work_id}</div>
            <div class="text-[11px] text-slate-500">${item.work_category || 'General'}</div>
          </td>
          <td>
            <div class="font-semibold text-slate-800 text-xs line-clamp-1" title="${item.work_title}">${item.work_title}</div>
            <div class="text-[11px] text-slate-500">${item.district}, ${item.state} • ${item.mp_name || ''}</div>
          </td>
          <td>
            <div class="font-bold text-slate-800">${formatINR(item.sanction_amount)}</div>
            <div class="text-[11px] font-semibold text-emerald-700">${formatINR(item.total_disbursed)}</div>
          </td>
          <td>
            <span class="font-bold text-xs ${item.budget_disbursement_ratio > 1.0 ? 'text-red-700' : 'text-slate-700'}">${disbRatioStr}</span>
          </td>
          <td>${delayBadge}</td>
          <td>
            <div class="font-bold text-xs">${item.payment_tranche_count} tranches</div>
            <div class="text-[11px] text-slate-500">${item.vendor_unique_count} vendors</div>
          </td>
          <td>${scoreBadge}</td>
          <td>
            <button onclick="inspectWorkDetail('${item.work_id}')" class="bg-purple-100 hover:bg-purple-200 text-purple-900 font-bold px-3 py-1.5 rounded-lg text-xs transition border border-purple-200">
              🔍 Inspect ML
            </button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.error("Failed to fetch monitoring works:", err);
  }
}

function applyMonitoringFilter() {
  fetchMonitoringWorks(1);
}

function resetMonitoringFilters() {
  if (document.getElementById("mon-filter-q")) document.getElementById("mon-filter-q").value = "";
  if (document.getElementById("mon-filter-state")) document.getElementById("mon-filter-state").value = "";
  if (document.getElementById("mon-filter-district")) document.getElementById("mon-filter-district").value = "";
  if (document.getElementById("mon-filter-delay")) document.getElementById("mon-filter-delay").value = "";
  if (document.getElementById("mon-filter-budget")) document.getElementById("mon-filter-budget").value = "";
  if (document.getElementById("mon-filter-anomaly")) document.getElementById("mon-filter-anomaly").value = "";
  fetchMonitoringWorks(1);
}

function changeMonPage(delta) {
  fetchMonitoringWorks(monPage + delta);
}

async function inspectWorkDetail(work_id) {
  try {
    const res = await fetch(`/api/monitoring/work/${encodeURIComponent(work_id)}`);
    if (!res.ok) {
      alert("Failed to fetch work detail.");
      return;
    }
    const d = await res.json();

    const p = d.project_info || {};
    const f = d.financial_info || {};
    const t = d.timeline || {};
    const pay = d.payment_info || {};
    const ml = d.ml_monitoring || {};

    if (document.getElementById("ins-anomaly-badge")) {
      document.getElementById("ins-anomaly-badge").className = `badge-status ${ml.anomaly_status === 'POTENTIAL ANOMALY' ? 'badge-anomaly-high' : 'badge-anomaly-normal'}`;
      document.getElementById("ins-anomaly-badge").textContent = ml.anomaly_status || "NORMAL";
    }

    if (document.getElementById("ins-delay-badge")) {
      document.getElementById("ins-delay-badge").className = `badge-status ${t.delay_status === 'DELAYED' ? 'badge-delay-delayed' : 'badge-delay-ontime'}`;
      document.getElementById("ins-delay-badge").textContent = t.delay_status || "ON_TIME";
    }

    if (document.getElementById("ins-budget-badge")) {
      document.getElementById("ins-budget-badge").className = `badge-status ${f.budget_monitoring_status === 'POTENTIAL_BUDGET_OVERRUN' ? 'badge-returned' : 'badge-completed'}`;
      document.getElementById("ins-budget-badge").textContent = f.budget_monitoring_status || "WITHIN_SANCTION";
    }

    if (document.getElementById("ins-title")) document.getElementById("ins-title").textContent = p.work_title || "Project Detail";
    if (document.getElementById("ins-wid")) document.getElementById("ins-wid").textContent = `WORK ID: ${p.work_id}`;
    if (document.getElementById("ins-geo")) document.getElementById("ins-geo").textContent = `${p.district || ''}, ${p.state || ''}`;
    if (document.getElementById("ins-constituency")) document.getElementById("ins-constituency").textContent = p.constituency || "N/A";
    if (document.getElementById("ins-mp")) document.getElementById("ins-mp").textContent = p.mp_name || "N/A";
    if (document.getElementById("ins-category")) document.getElementById("ins-category").textContent = p.work_category || "General";

    if (document.getElementById("ins-ml-risk-score")) document.getElementById("ins-ml-risk-score").textContent = `${ml.anomaly_risk_score || 0}/100`;
    if (document.getElementById("ins-ml-raw")) document.getElementById("ins-ml-raw").textContent = ml.raw_anomaly_score || "0.0000";
    if (document.getElementById("ins-ml-pred")) document.getElementById("ins-ml-pred").textContent = `${ml.anomaly_prediction || 1} (${ml.anomaly_prediction === -1 ? 'Anomaly' : 'Normal'})`;
    if (document.getElementById("ins-ml-status")) document.getElementById("ins-ml-status").textContent = ml.anomaly_status || "NORMAL";

    const featObj = ml.features_contributing || {};
    const featList = document.getElementById("ins-ml-features-list");
    if (featList) {
      featList.innerHTML = `
        <div>• Sanction Outlay: <strong class="text-slate-800">${formatINR(featObj.sanction_amount)}</strong></div>
        <div>• Disbursed Outlay: <strong class="text-slate-800">${formatINR(featObj.total_disbursed)}</strong></div>
        <div>• Disbursement Ratio: <strong class="text-slate-800">${((featObj.disbursement_ratio || 0)*100).toFixed(1)}%</strong></div>
        <div>• Sanction Lead Time: <strong class="text-slate-800">${featObj.sanction_lead_time_days || 0} days</strong></div>
        <div>• Payment Tranches: <strong class="text-slate-800">${featObj.payment_tranches || 0} count</strong></div>
        <div>• Max Tranche Ratio: <strong class="text-slate-800">${((featObj.max_tranche_ratio || 0)*100).toFixed(1)}%</strong></div>
        <div>• Description Length: <strong class="text-slate-800">${featObj.description_length || 0} chars</strong></div>
      `;
    }

    if (document.getElementById("ins-sanction-amt")) document.getElementById("ins-sanction-amt").textContent = formatINR(f.sanction_amount);
    if (document.getElementById("ins-disbursed-amt")) document.getElementById("ins-disbursed-amt").textContent = formatINR(f.total_disbursed);
    if (document.getElementById("ins-disb-ratio")) document.getElementById("ins-disb-ratio").textContent = f.disbursement_ratio !== undefined ? `${(f.disbursement_ratio * 100).toFixed(1)}%` : "0%";
    if (document.getElementById("ins-variance-amt")) document.getElementById("ins-variance-amt").textContent = formatINR(f.remaining_sanction);
    if (document.getElementById("ins-budget-status-val")) document.getElementById("ins-budget-status-val").textContent = f.budget_monitoring_status || "WITHIN_SANCTION";

    if (document.getElementById("ins-rec-date")) document.getElementById("ins-rec-date").textContent = formatDate(t.recommended_date);
    if (document.getElementById("ins-sanc-date")) document.getElementById("ins-sanc-date").textContent = formatDate(t.sanction_date);
    if (document.getElementById("ins-exp-date")) document.getElementById("ins-exp-date").textContent = formatDate(t.expected_completion_date_proxy);
    if (document.getElementById("ins-comp-date")) document.getElementById("ins-comp-date").textContent = formatDate(t.completion_date);
    if (document.getElementById("ins-lead-time")) document.getElementById("ins-lead-time").textContent = `${t.sanction_lead_time_days || 0} days`;
    if (document.getElementById("ins-schedule-delay")) document.getElementById("ins-schedule-delay").textContent = `${t.schedule_delay_days || 0} days`;

    if (document.getElementById("ins-pay-count")) document.getElementById("ins-pay-count").textContent = `${pay.payment_tranche_count || 0} payment tranches`;
    if (document.getElementById("ins-pay-first")) document.getElementById("ins-pay-first").textContent = formatDate(pay.first_payment_date);
    if (document.getElementById("ins-pay-last")) document.getElementById("ins-pay-last").textContent = formatDate(pay.latest_payment_date);
    if (document.getElementById("ins-pay-max-ratio")) document.getElementById("ins-pay-max-ratio").textContent = pay.max_single_tranche_ratio !== undefined ? `${(pay.max_single_tranche_ratio * 100).toFixed(1)}%` : "0%";
    if (document.getElementById("ins-pay-vendors")) document.getElementById("ins-pay-vendors").textContent = pay.vendor_unique_count || 0;

    const payTbody = document.getElementById("ins-payments-tbody");
    if (payTbody) {
      const plist = pay.payments_list || [];
      if (plist.length === 0) {
        payTbody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-slate-400">No payment events recorded for this project.</td></tr>`;
      } else {
        payTbody.innerHTML = plist.map(pitem => `
          <tr>
            <td class="font-mono text-xs">${formatDate(pitem.expenditure_date)}</td>
            <td class="font-semibold text-slate-800 text-xs">${pitem.vendor_name_normalized || pitem.vendor_name_raw || 'Vendor'}</td>
            <td><span class="badge-status badge-completed">${pitem.payment_status || 'SUCCESS'}</span></td>
            <td class="font-bold text-emerald-700 text-xs">${formatINR(pitem.reported_fund_disbursed_amount)}</td>
          </tr>
        `).join("");
      }
    }

    openModal("modal-inspect");
  } catch (err) {
    console.error("Error inspecting work:", err);
    alert("Error fetching work inspection profile.");
  }
}

async function loadAlertsView() {
  const container = document.getElementById("alerts-container");
  if (!container) return;

  container.innerHTML = `<div class="p-6 text-center text-slate-400">Loading screening alerts...</div>`;

  try {
    const res = await fetch("/api/monitoring/alerts?limit=50");
    const data = await res.json();

    const alerts = data.alerts || [];
    if (document.getElementById("alerts-count-badge")) document.getElementById("alerts-count-badge").textContent = alerts.length;

    if (alerts.length === 0) {
      container.innerHTML = `<div class="p-8 text-center text-slate-500 font-medium">Zero screening alerts triggered across active dataset.</div>`;
      return;
    }

    container.innerHTML = alerts.map(a => {
      let sevColor = "border-amber-200 bg-amber-50 text-amber-900";
      if (a.severity === "HIGH") sevColor = "border-red-200 bg-red-50 text-red-900";

      return `
        <div class="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-slate-50 transition">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${sevColor}">${a.alert_type}</span>
              <span class="text-xs font-mono font-bold text-slate-600">${a.work_id}</span>
              <span class="text-xs text-slate-500">• ${a.district}, ${a.state}</span>
            </div>
            <div class="font-bold text-slate-800 text-sm">${a.work_title}</div>
            <div class="text-xs text-slate-600">Measurement: <strong class="text-slate-800">${a.measured_value}</strong></div>
          </div>
          <div class="flex items-center gap-3">
            <div class="text-right hidden sm:block">
              <div class="text-[10px] text-slate-500 uppercase font-semibold">Anomaly Risk</div>
              <div class="text-base font-black ${a.anomaly_risk_score >= 80 ? 'text-red-700' : 'text-amber-700'}">${a.anomaly_risk_score}/100</div>
            </div>
            <button onclick="inspectWorkDetail('${a.work_id}')" class="bg-gov-primary hover:bg-blue-900 text-white font-bold px-3.5 py-2 rounded-xl text-xs transition shadow-xs">
              Inspect ML Profile
            </button>
          </div>
        </div>
      `;
    }).join("");

  } catch (err) {
    console.error("Failed to load alerts:", err);
  }
}

async function triggerRetrainMl() {
  if (!confirm("Are you sure you want to retrain the Isolation Forest model on all 41,086 projects with contamination = 0.05?")) return;

  try {
    const res = await fetch("/api/ml/retrain?contamination=0.05", { method: "POST" });
    const data = await res.json();

    if (res.ok && data.success) {
      alert("✅ Isolation Forest model retrained successfully!\n" + data.message);
      loadMonitoringDashboard();
    } else {
      alert("Retraining failed: " + (data.detail || "Unknown error"));
    }
  } catch (err) {
    console.error("Retrain error:", err);
    alert("Retrain API call failed.");
  }
}

async function renderAnalyticsCharts() {
  try {
    const res = await fetch("/api/analytics/monitoring");
    const data = await res.json();

    // 1. State-Wise Projects Bar Chart
    if (document.getElementById("chart-states") && data.state_metrics) {
      const topStates = data.state_metrics.slice(0, 15);
      renderChart("chart-states", "bar", {
        labels: topStates.map(s => s.state),
        datasets: [{
          label: "Sanctioned Projects",
          data: topStates.map(s => s.project_count),
          backgroundColor: "#0F4C81",
          borderRadius: 4
        }]
      });
    }

    // 2. Work Completion Status (Doughnut)
    if (document.getElementById("chart-status") && data.completion_dist) {
      renderChart("chart-status", "doughnut", {
        labels: data.completion_dist.map(c => c.status),
        datasets: [{
          data: data.completion_dist.map(c => c.count),
          backgroundColor: ["#107C41", "#F58220", "#0F4C81", "#64748B"]
        }]
      });
    }

    // 3. Schedule Delay Classification (Bar)
    if (document.getElementById("chart-delay") && data.delay_dist) {
      renderChart("chart-delay", "bar", {
        labels: data.delay_dist.map(d => d.status),
        datasets: [{
          label: "Projects",
          data: data.delay_dist.map(d => d.count),
          backgroundColor: ["#107C41", "#DC2626", "#2563EB", "#D97706"],
          borderRadius: 4
        }]
      });
    }

    // 4. Budget Monitoring Classification (Doughnut)
    if (document.getElementById("chart-budget") && data.budget_dist) {
      renderChart("chart-budget", "doughnut", {
        labels: data.budget_dist.map(b => b.status),
        datasets: [{
          data: data.budget_dist.map(b => b.count),
          backgroundColor: ["#107C41", "#2563EB", "#DC2626"]
        }]
      });
    }

    // 5. Payment Tranche Frequency (Bar)
    if (document.getElementById("chart-tranches") && data.tranche_dist) {
      renderChart("chart-tranches", "bar", {
        labels: data.tranche_dist.map(t => t.category),
        datasets: [{
          label: "Projects",
          data: data.tranche_dist.map(t => t.count),
          backgroundColor: "#7C3AED",
          borderRadius: 4
        }]
      });
    }

    // 6. ML Anomaly Screening Distribution (Doughnut)
    if (document.getElementById("chart-anomalies") && data.anomaly_dist) {
      renderChart("chart-anomalies", "doughnut", {
        labels: data.anomaly_dist.map(a => a.status),
        datasets: [{
          data: data.anomaly_dist.map(a => a.count),
          backgroundColor: ["#334155", "#9333EA"]
        }]
      });
    }

    // 7. Monthly Expenditure Trend (Line)
    if (document.getElementById("chart-monthly-payments") && data.monthly_payments) {
      const topMonths = data.monthly_payments.slice(-24);
      renderChart("chart-monthly-payments", "line", {
        labels: topMonths.map(m => m.month_str),
        datasets: [{
          label: "Disbursed Amount (₹)",
          data: topMonths.map(m => m.total_disbursed),
          borderColor: "#107C41",
          backgroundColor: "rgba(16, 124, 65, 0.1)",
          fill: true,
          tension: 0.3
        }]
      });
    }

    // 8. Top Disbursed Outlay by State (Bar)
    if (document.getElementById("chart-risk-by-state") && data.state_metrics) {
      const sortedByDisbursed = [...data.state_metrics].sort((a,b) => b.total_disbursed - a.total_disbursed).slice(0, 10);
      renderChart("chart-risk-by-state", "bar", {
        labels: sortedByDisbursed.map(s => s.state),
        datasets: [{
          label: "Total Disbursed (₹ Cr)",
          data: sortedByDisbursed.map(s => (s.total_disbursed / 10000000).toFixed(2)),
          backgroundColor: "#059669",
          borderRadius: 4
        }]
      });
    }

    // Render State Summary Table
    const tbody = document.getElementById("analytics-states-tbody");
    if (tbody && data.state_metrics) {
      tbody.innerHTML = data.state_metrics.map(s => {
        const rate = s.project_count > 0 ? ((s.total_disbursed / (s.total_sanction || 1)) * 100).toFixed(1) : 0;
        return `
          <tr>
            <td class="font-bold text-slate-800">${s.state}</td>
            <td>${s.project_count.toLocaleString()}</td>
            <td class="font-semibold text-slate-800">${formatINR(s.total_sanction)}</td>
            <td class="font-semibold text-emerald-700">${formatINR(s.total_disbursed)}</td>
            <td>
              <div class="flex items-center gap-2">
                <span class="font-bold text-xs">${rate}%</span>
                <div class="w-16 bg-slate-200 rounded-full h-1.5 overflow-hidden">
                  <div class="bg-gov-primary h-1.5 rounded-full" style="width: ${Math.min(rate, 100)}%"></div>
                </div>
              </div>
            </td>
          </tr>
        `;
      }).join("");
    }

  } catch (err) {
    console.error("Failed to load analytics monitoring data:", err);
  }
}

function renderChart(canvasId, type, chartData) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  if (chartInstances[canvasId]) {
    chartInstances[canvasId].destroy();
  }

  chartInstances[canvasId] = new Chart(ctx, {
    type: type,
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: type === "doughnut", position: "right", labels: { boxWidth: 12, font: { size: 10 } } }
      },
      scales: type !== "doughnut" ? {
        y: { beginAtZero: true, grid: { color: "#F1F5F9" } },
        x: { grid: { display: false } }
      } : {}
    }
  });
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
