const fs = require('fs');

// Read app.js
const appJs = fs.readFileSync('static/js/app.js', 'utf8');

// Mock browser globals
global.window = {
  lucide: { createIcons: () => {} }
};

global.document = {
  getElementById: (id) => {
    return {
      textContent: '',
      innerHTML: '',
      value: '',
      style: {},
      classList: { add: () => {}, remove: () => {} }
    };
  },
  addEventListener: (event, handler) => {
    if (event === 'DOMContentLoaded') {
      handler();
    }
  }
};

global.fetch = async (url) => {
  console.log(`FETCH CALLED: ${url}`);
  if (url === '/api/metadata/geography') {
    return {
      ok: true,
      json: async () => ({
        states: ['Madhya Pradesh'],
        districts: [{ state: 'Madhya Pradesh', district: 'Agar-Malwa' }],
        constituencies: [],
        mps: [{ mp_name: 'Test MP', constituency: 'Test', state: 'Madhya Pradesh' }],
        categories: [],
        agencies: []
      })
    };
  }
  if (url === '/api/analytics/overview') {
    return {
      ok: true,
      json: async () => ({
        kpis: {
          total_works: 41086,
          total_payment_events: 49990,
          total_sanction_amount: 21057615515.5,
          total_disbursed_amount: 14812622710.57,
          completed_works: 19304,
          ongoing_works: 21782,
          completion_rate_pct: 47.0,
          live_works_count: 0
        },
        state_breakdown: [],
        status_breakdown: [],
        category_breakdown: []
      })
    };
  }
  if (url.includes('/api/metadata/districts')) {
    return { ok: true, json: async () => ({ districts: ['Agar-Malwa'] }) };
  }
  if (url.includes('/api/da/dashboard')) {
    return {
      ok: true,
      json: async () => ({
        district: 'Agar-Malwa',
        state: 'Madhya Pradesh',
        kpis: { historical_district_works: 9, active_live_works: 0, district_sanction_amount: 7600000, district_disbursed_amount: 4850000, district_completed: 5, district_ongoing: 4 },
        pending_recommendations: [],
        active_live_works: [],
        historical_district_works: [],
        agencies: []
      })
    };
  }
  return { ok: true, json: async () => ({}) };
};

try {
  eval(appJs);
  console.log("JS EXECUTION SUCCESS!");
} catch (e) {
  console.error("JS EXECUTION ERROR:", e);
}
