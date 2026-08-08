# Emergency Event Report Examples

Worked examples across three triage categories, using a consistent report structure so the difference sits in the content rather than the format.

## Triage logic applied

| Category | Test | Next step |
|---|---|---|
| **Awareness** | Known state, no immediate life safety risk, impact contained or already owned by another party | Log and monitor |
| **Verification required** | Potential for significant impact, but source is single, unconfirmed or contradicted by other data | Confirm the facts |
| **Action required** | Confirmed or highly credible, life safety or critical infrastructure at risk, response window measured in minutes to hours | Respond and decide |

Escalation drivers: impact to human life, scale of impact, and timeliness of response needed.

---

## 1. Awareness

### EVT-2026-0417

| Field | Detail |
|---|---|
| **Type** | Severe weather watch |
| **Location** | Tararua Range and eastern Kāpiti hill country |
| **Reported** | 08 Aug 2026, 06:15 |
| **Source** | MetService heavy rain watch (official feed) |
| **Life safety** | None identified |
| **Scale** | District-wide, low intensity |
| **Timeliness** | Monitor, next review at 12:00 |

**Description**
Heavy rain watch issued for the 24 hours from 18:00 today. Forecast accumulations below warning thresholds. No current road or river impacts.

**Rationale**
Forecast only, below warning criteria. Logged for situational awareness and to inform duty roster planning.

### EVT-2026-0418

| Field | Detail |
|---|---|
| **Type** | Road obstruction |
| **Location** | SH58, westbound lane near Haywards |
| **Reported** | 08 Aug 2026, 07:40 |
| **Source** | Contractor field crew |
| **Life safety** | None, traffic controls in place |
| **Scale** | Single site, minor delay |
| **Timeliness** | No response required |

**Description**
Small slip of loose material onto shoulder. Contractor on site, area coned, one lane running under stop/go. Clearance expected within two hours.

**Rationale**
Already owned and actively managed by the responsible party. Recorded so it is visible if weather conditions change.

---

## 2. Verification required

### EVT-2026-0419

| Field | Detail |
|---|---|
| **Type** | Suspected hazardous substance |
| **Location** | Residential street adjacent to a primary school, Paraparaumu |
| **Reported** | 08 Aug 2026, 08:52 |
| **Source** | Two social media posts, no caller to 111 logged |
| **Life safety** | Potentially high if confirmed, given proximity to children |
| **Scale** | Unknown, potentially one to two blocks |
| **Timeliness** | Verify within 15 minutes |

**Description**
Posts describe a strong gas odour near the school boundary at drop-off time. No utility outage or works notified in the area. No corroborating reports from school staff.

**Rationale**
Consequence if true is severe, but the source is unverified and second-hand. Action is to contact the school office and the gas network operator to confirm before any escalation.

### EVT-2026-0420

| Field | Detail |
|---|---|
| **Type** | Possible wastewater overflow |
| **Location** | Stream outlet, coastal reserve |
| **Reported** | 08 Aug 2026, 09:10 |
| **Source** | Single member of the public via council contact centre |
| **Life safety** | Low, but public health risk if confirmed and the beach is in use |
| **Scale** | Localised, possible recreational water contamination |
| **Timeliness** | Verify within two hours, before peak public use |

**Description**
Caller reports discoloured water and odour at the outlet following overnight rain. SCADA shows no pump station alarms. No overflow consent notification received.

**Rationale**
Telemetry contradicts the report, so a field check is needed to resolve the conflict before public notification is considered.

---

## 3. Action required

### EVT-2026-0421

| Field | Detail |
|---|---|
| **Type** | Landslide with structural impact |
| **Location** | Hillside residential property, Pukerua Bay |
| **Reported** | 08 Aug 2026, 09:35 |
| **Source** | 111 call, confirmed by first responding crew on scene |
| **Life safety** | Confirmed, one person unaccounted for |
| **Scale** | Three properties, approximately eight residents affected |
| **Timeliness** | Immediate |

**Description**
Large slip has struck the rear of an occupied dwelling. Two occupants accounted for and evacuated. One person unaccounted for. Two neighbouring properties assessed as at risk of further movement.

**Rationale**
Confirmed life safety risk with an active search component and ongoing ground instability. Requires immediate multi-agency response, cordon, geotechnical assessment and evacuation of neighbouring dwellings.

### EVT-2026-0422

| Field | Detail |
|---|---|
| **Type** | Flash flooding and isolation of a community |
| **Location** | Rural settlement, Ōtaki Gorge Road corridor |
| **Reported** | 08 Aug 2026, 09:48 |
| **Source** | Regional council river telemetry plus confirmation from two residents and a police unit |
| **Life safety** | High, vulnerable population isolated with rising water |
| **Scale** | Approximately 100 people, critical facility affected |
| **Timeliness** | Immediate, evacuation decision needed within the hour while the river remains passable by helicopter |

**Description**
River level has exceeded the stopbank trigger threshold and is still rising. The single access road is under water and impassable. Approximately 40 households are cut off, including a residential care facility with 12 residents, several with mobility needs. Power supply is intermittent.

**Rationale**
Confirmed by instrument data and multiple human sources, with a closing response window and a known vulnerable population. Requires immediate activation, welfare planning and an evacuation decision.

---

## Note for triage users

The pattern that separates the categories cleanly is the state of the decision, not how alarming the description sounds:

- **Awareness**: known state, no pending decision.
- **Verification required**: unknown state blocking a decision.
- **Action required**: known state with a decision that expires.
