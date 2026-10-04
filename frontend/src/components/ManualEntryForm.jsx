import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

function splitEvenly(total, n) {
  const base = Math.round((total / n) * 10) / 10;
  const values = new Array(n).fill(base);
  const drift = Math.round((total - base * n) * 10) / 10;
  values[0] = Math.round((values[0] + drift) * 10) / 10;
  return values;
}

function Field({ label, unit, hint, error, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, minWidth: 160 }}>
      <span>
        {label} {unit && <span style={{ color: "#9aa4b2" }}>({unit})</span>}
      </span>
      {children}
      {hint && !error && <span style={{ fontSize: 11, color: "#9aa4b2" }}>{hint}</span>}
      {error && <span style={{ fontSize: 11, color: "#ff8a8a" }}>{error}</span>}
    </label>
  );
}

function numField(value, onChange) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
    />
  );
}

export default function ManualEntryForm({ original, presets, onSubmit, loading }) {
  const [scenario, setScenario] = useState(original);
  const [expandSolar, setExpandSolar] = useState(false);
  const [expandWind, setExpandWind] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [corrections, setCorrections] = useState([]);
  const [checking, setChecking] = useState(false);
  const [facts, setFacts] = useState(null);
  const [factsLoading, setFactsLoading] = useState(false);

  function patch(fields) {
    setScenario((s) => ({ ...s, ...fields }));
  }

  function resetToGenerated() {
    setScenario(original);
  }

  async function refreshFacts() {
    setFactsLoading(true);
    try {
      const { facts: f } = await api.normalizeScenario(scenario);
      setFacts(f);
    } finally {
      setFactsLoading(false);
    }
  }

  useEffect(() => {
    refreshFacts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setAggregateSolar(output_mw, forecast_mw) {
    const farms = expandSolar
      ? scenario.solar_farms
      : scenario.solar_farms.map((f, i) => ({
          ...f,
          output_mw: splitEvenly(output_mw ?? scenario.solar_output_mw, scenario.solar_farms.length)[i],
          forecast_mw: splitEvenly(forecast_mw ?? scenario.solar_forecast_mw, scenario.solar_farms.length)[i],
        }));
    patch({
      solar_output_mw: output_mw ?? scenario.solar_output_mw,
      solar_forecast_mw: forecast_mw ?? scenario.solar_forecast_mw,
      solar_farms: farms,
    });
  }

  function setAggregateWind(output_mw, forecast_mw) {
    const farms = expandWind
      ? scenario.wind_farms
      : scenario.wind_farms.map((f, i) => ({
          ...f,
          output_mw: splitEvenly(output_mw ?? scenario.wind_output_mw, scenario.wind_farms.length)[i],
          forecast_mw: splitEvenly(forecast_mw ?? scenario.wind_forecast_mw, scenario.wind_farms.length)[i],
        }));
    patch({
      wind_output_mw: output_mw ?? scenario.wind_output_mw,
      wind_forecast_mw: forecast_mw ?? scenario.wind_forecast_mw,
      wind_farms: farms,
    });
  }

  function setSolarFarmField(index, field, value) {
    const farms = scenario.solar_farms.map((f, i) => (i === index ? { ...f, [field]: value } : f));
    const output_mw = Math.round(farms.reduce((sum, f) => sum + f.output_mw, 0) * 10) / 10;
    const forecast_mw = Math.round(farms.reduce((sum, f) => sum + f.forecast_mw, 0) * 10) / 10;
    patch({ solar_farms: farms, solar_output_mw: output_mw, solar_forecast_mw: forecast_mw });
  }

  function setWindFarmField(index, field, value) {
    const farms = scenario.wind_farms.map((f, i) => (i === index ? { ...f, [field]: value } : f));
    const output_mw = Math.round(farms.reduce((sum, f) => sum + f.output_mw, 0) * 10) / 10;
    const forecast_mw = Math.round(farms.reduce((sum, f) => sum + f.forecast_mw, 0) * 10) / 10;
    patch({ wind_farms: farms, wind_output_mw: output_mw, wind_forecast_mw: forecast_mw });
  }

  function setBatteryField(index, field, value) {
    const batteries = scenario.batteries.map((b, i) => (i === index ? { ...b, [field]: value } : b));
    patch({ batteries });
  }

  function toggleEvent(key, on) {
    const events = new Set(scenario.events);
    if (on) events.add(key);
    else events.delete(key);
    const next = { events: Array.from(events) };
    if (key === "storm_alert") {
      next.storm_alert = on;
      next.weather_forecast = on ? "storm" : "clear";
    }
    if (key === "battery_2_offline") {
      next.batteries = scenario.batteries.map((b) => (b.id === "battery_2" ? { ...b, available: !on } : b));
    }
    patch(next);
  }

  const errors = useMemo(() => {
    const e = {};
    const positive = (v, field, label) => {
      if (v === "" || v === null || Number.isNaN(v)) e[field] = `${label} is required`;
      else if (v < 0) e[field] = `${label} must be >= 0`;
    };
    positive(scenario.solar_output_mw, "solar_output_mw", "Solar output");
    positive(scenario.wind_output_mw, "wind_output_mw", "Wind output");
    positive(scenario.solar_forecast_mw, "solar_forecast_mw", "Solar forecast");
    positive(scenario.wind_forecast_mw, "wind_forecast_mw", "Wind forecast");
    positive(scenario.base_demand_mw, "base_demand_mw", "Base demand");
    positive(scenario.base_demand_forecast_mw, "base_demand_forecast_mw", "Base demand forecast");
    positive(scenario.industrial_demand_mw, "industrial_demand_mw", "Industrial demand");
    positive(scenario.electricity_price_per_mwh, "electricity_price_per_mwh", "Electricity price");
    positive(scenario.carbon_price_per_ton, "carbon_price_per_ton", "Carbon price");
    positive(scenario.demand_response_incentive_per_mwh, "demand_response_incentive_per_mwh", "DR incentive");
    positive(scenario.transmission_headroom_mw, "transmission_headroom_mw", "Transmission headroom");
    positive(scenario.previous_floor_pct, "previous_floor_pct", "Previous floor");
    if (scenario.grid_frequency_hz === "" || scenario.grid_frequency_hz === null) e.grid_frequency_hz = "Grid frequency is required";
    scenario.batteries.forEach((b, i) => {
      if (b.state_of_charge_pct === "" || b.state_of_charge_pct < 0 || b.state_of_charge_pct > 100) {
        e[`battery_${i}_soc`] = "State of charge must be 0-100";
      }
    });
    return e;
  }, [scenario]);

  const isValid = Object.keys(errors).length === 0;
  const liveTotalDemand = Math.round(((Number(scenario.base_demand_mw) || 0) + (Number(scenario.industrial_demand_mw) || 0)) * 10) / 10;

  async function handleSend() {
    setChecking(true);
    try {
      const { scenario: normalized, corrections: found } = await api.normalizeScenario(scenario);
      setScenario(normalized);
      setCorrections(found);
      onSubmit(normalized);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="panel">
      <h2>Manual Entry</h2>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Scenario</h2>
        <div className="row">
          <Field label="Objective">
            <select value={scenario.objective || ""} onChange={(e) => patch({ objective: e.target.value || null })}>
              <option value="">none (cost_efficiency applies)</option>
              {presets.objectives.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </Field>
          <button type="button" className="secondary" onClick={resetToGenerated}>Reset to generated</button>
          <button type="button" className="secondary" onClick={refreshFacts} disabled={factsLoading}>
            {factsLoading ? "Checking…" : "Refresh physics facts"}
          </button>
        </div>
        {facts && (
          <div className="row" style={{ marginTop: 10, fontSize: 13 }}>
            <span className="badge" style={{ background: "#1f2b45", color: "#8fb4ff" }}>
              generation {facts.total_generation_mw} MW
            </span>
            <span className="badge" style={{ background: facts.position === "surplus" ? "#1e4620" : facts.position === "shortfall" ? "#4a1f23" : "#1f2b45", color: facts.position === "surplus" ? "#6fe382" : facts.position === "shortfall" ? "#ff8a8a" : "#8fb4ff" }}>
              {facts.position}: {facts.net_position_mw} MW
            </span>
            <span style={{ color: "#9aa4b2" }}>
              battery discharge available: {facts.total_discharge_available_mw} MW · charge headroom: {facts.total_charge_headroom_mw} MW
            </span>
          </div>
        )}
      </div>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Generation</h2>
        <div className="row">
          <Field label="Total solar output" unit="MW" error={errors.solar_output_mw} hint="0-200 typical">
            {numField(scenario.solar_output_mw, (v) => setAggregateSolar(v, undefined))}
          </Field>
          <Field label="Solar forecast" unit="MW" error={errors.solar_forecast_mw}>
            {numField(scenario.solar_forecast_mw, (v) => setAggregateSolar(undefined, v))}
          </Field>
          <Field label="Total wind output" unit="MW" error={errors.wind_output_mw} hint="0-200 typical">
            {numField(scenario.wind_output_mw, (v) => setAggregateWind(v, undefined))}
          </Field>
          <Field label="Wind forecast" unit="MW" error={errors.wind_forecast_mw}>
            {numField(scenario.wind_forecast_mw, (v) => setAggregateWind(undefined, v))}
          </Field>
        </div>

        <div className="row" style={{ marginTop: 10 }}>
          <button type="button" className="secondary" onClick={() => setExpandSolar((v) => !v)}>
            {expandSolar ? "Collapse" : "Expand"} solar farms (5)
          </button>
          <button type="button" className="secondary" onClick={() => setExpandWind((v) => !v)}>
            {expandWind ? "Collapse" : "Expand"} wind farms (3)
          </button>
        </div>

        {expandSolar && (
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>Farm</th><th>Capacity (MW)</th><th>Output (MW)</th><th>Forecast (MW)</th></tr></thead>
            <tbody>
              {scenario.solar_farms.map((f, i) => (
                <tr key={f.id}>
                  <td>{f.id}</td>
                  <td>{numField(f.capacity_mw, (v) => setSolarFarmField(i, "capacity_mw", v))}</td>
                  <td>{numField(f.output_mw, (v) => setSolarFarmField(i, "output_mw", v))}</td>
                  <td>{numField(f.forecast_mw, (v) => setSolarFarmField(i, "forecast_mw", v))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {expandWind && (
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>Farm</th><th>Capacity (MW)</th><th>Output (MW)</th><th>Forecast (MW)</th></tr></thead>
            <tbody>
              {scenario.wind_farms.map((f, i) => (
                <tr key={f.id}>
                  <td>{f.id}</td>
                  <td>{numField(f.capacity_mw, (v) => setWindFarmField(i, "capacity_mw", v))}</td>
                  <td>{numField(f.output_mw, (v) => setWindFarmField(i, "output_mw", v))}</td>
                  <td>{numField(f.forecast_mw, (v) => setWindFarmField(i, "forecast_mw", v))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Demand</h2>
        <div className="row">
          <Field label="Base demand" unit="MW" error={errors.base_demand_mw} hint="excludes industrial load">
            {numField(scenario.base_demand_mw, (v) => patch({ base_demand_mw: v }))}
          </Field>
          <Field label="Base demand forecast" unit="MW" error={errors.base_demand_forecast_mw}>
            {numField(scenario.base_demand_forecast_mw, (v) => patch({ base_demand_forecast_mw: v }))}
          </Field>
          <Field label="Industrial demand" unit="MW" error={errors.industrial_demand_mw}>
            {numField(scenario.industrial_demand_mw, (v) => patch({ industrial_demand_mw: v }))}
          </Field>
          <Field label="Total demand (computed)" unit="MW" hint="base + industrial — read-only, recomputed by the server before every run">
            <input type="number" value={liveTotalDemand} disabled />
          </Field>
        </div>
      </div>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Prices</h2>
        <div className="row">
          <Field label="Electricity price" unit="$/MWh" error={errors.electricity_price_per_mwh}>
            {numField(scenario.electricity_price_per_mwh, (v) => patch({ electricity_price_per_mwh: v }))}
          </Field>
          <Field label="Carbon price" unit="$/ton" error={errors.carbon_price_per_ton}>
            {numField(scenario.carbon_price_per_ton, (v) => patch({ carbon_price_per_ton: v }))}
          </Field>
          <Field label="Demand response incentive" unit="$/MWh" error={errors.demand_response_incentive_per_mwh} hint="not in the brief's table, but required">
            {numField(scenario.demand_response_incentive_per_mwh, (v) => patch({ demand_response_incentive_per_mwh: v }))}
          </Field>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <Field label="Buy price" unit="$/MWh" hint="computed: electricity price + spread — what a purchase costs">
            <input type="number" value={scenario.buy_price_per_mwh} disabled />
          </Field>
          <Field label="Sell price" unit="$/MWh" hint="computed: electricity price - spread — what a sale earns">
            <input type="number" value={scenario.sell_price_per_mwh} disabled />
          </Field>
        </div>
      </div>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Batteries</h2>
        <div className="row" style={{ gap: 20 }}>
          {scenario.batteries.map((b, i) => (
            <div key={b.id} className="row" style={{ gap: 10 }}>
              <strong>{b.id}</strong>
              <Field label="State of charge" unit="%" error={errors[`battery_${i}_soc`]}>
                {numField(b.state_of_charge_pct, (v) => setBatteryField(i, "state_of_charge_pct", v))}
              </Field>
              <label style={{ fontSize: 13 }}>
                <input type="checkbox" checked={b.available} onChange={(e) => setBatteryField(i, "available", e.target.checked)} /> Available
              </label>
            </div>
          ))}
        </div>
      </div>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Grid</h2>
        <div className="row">
          <Field label="Line rating" unit="MW" hint="fixed interconnection capacity — read-only">
            <input type="number" value={scenario.transmission_constraint_mw} disabled />
          </Field>
          <Field label="Transmission headroom" unit="MW" error={errors.transmission_headroom_mw} hint="remaining net-flow capacity this tick — normally = line rating">
            {numField(scenario.transmission_headroom_mw, (v) => patch({ transmission_headroom_mw: v }))}
          </Field>
          <Field label="Grid frequency" unit="Hz" error={errors.grid_frequency_hz} hint="stable band is 49.5-50.5; set outside it to test rule_7">
            {numField(scenario.grid_frequency_hz, (v) => patch({ grid_frequency_hz: v }))}
          </Field>
        </div>
      </div>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Events</h2>
        <div className="row">
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={scenario.storm_alert} onChange={(e) => toggleEvent("storm_alert", e.target.checked)} /> Storm alert
          </label>
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={scenario.events.includes("battery_2_offline")} onChange={(e) => toggleEvent("battery_2_offline", e.target.checked)} /> Battery offline (battery_2)
          </label>
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={scenario.events.includes("transmission_at_capacity")} onChange={(e) => toggleEvent("transmission_at_capacity", e.target.checked)} /> Line constrained
          </label>
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={scenario.events.includes("demand_surge")} onChange={(e) => toggleEvent("demand_surge", e.target.checked)} /> Demand surge
          </label>
        </div>
      </div>

      <div className="panel" style={{ background: "#14181e" }}>
        <h2>Reserve</h2>
        <div className="row">
          <Field label="Previous floor" unit="%" error={errors.previous_floor_pct} hint="default 25">
            {numField(scenario.previous_floor_pct, (v) => patch({ previous_floor_pct: v }))}
          </Field>
        </div>
      </div>

      <details open={advancedOpen} onToggle={(e) => setAdvancedOpen(e.target.open)} className="panel" style={{ background: "#14181e" }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>Advanced — expected-behavior override</summary>
        <p style={{ fontSize: 12, color: "#9aa4b2" }}>Leave as-is to use the heuristic-derived tag from the generated scenario.</p>
        <div className="row" style={{ marginTop: 8 }}>
          <Field label="Expected floor min" unit="%">
            {numField(scenario.expected_floor_min_pct, (v) => patch({ expected_floor_min_pct: v }))}
          </Field>
          <Field label="Expected floor max" unit="%">
            {numField(scenario.expected_floor_max_pct, (v) => patch({ expected_floor_max_pct: v }))}
          </Field>
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={scenario.expected_emergency} onChange={(e) => patch({ expected_emergency: e.target.checked })} /> Expected emergency
          </label>
        </div>
        <Field label="Expected ladder step" hint="free text">
          <input type="text" value={scenario.expected_ladder_step} onChange={(e) => patch({ expected_ladder_step: e.target.value })} style={{ width: "100%" }} />
        </Field>
        <Field label="Expected behavior narrative" hint="free text">
          <input type="text" value={scenario.expected_behavior} onChange={(e) => patch({ expected_behavior: e.target.value })} style={{ width: "100%" }} />
        </Field>
      </details>

      {corrections.length > 0 && (
        <div className="panel" style={{ background: "#3a2a1f", borderColor: "#f5a666" }}>
          <h2 style={{ color: "#f5a666" }}>Auto-corrected before sending</h2>
          <ul style={{ fontSize: 13, margin: 0, paddingLeft: 18, color: "#f5a666" }}>
            {corrections.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

      <div className="row" style={{ marginTop: 10 }}>
        <button onClick={handleSend} disabled={!isValid || loading || checking}>
          {checking ? "Checking…" : loading ? "Sending…" : "Send to Orchestrator"}
        </button>
        {!isValid && <span style={{ fontSize: 12, color: "#ff8a8a" }}>{Object.keys(errors).length} field(s) need fixing</span>}
      </div>
    </div>
  );
}
