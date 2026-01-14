# AWS Cost Anomaly Detection

> Intelligent serverless cost monitoring that catches billing surprises before they catch you

Stop getting surprised by unexpected AWS bills. This system uses statistical anomaly detection to automatically identify unusual spending patterns and alert you with detailed root cause analysis—all for less than the cost of a coffee per month.

## Why This Matters

You wake up to an AWS bill that's 3x higher than expected. What happened? Which service spiked? When did it start?

**This project answers those questions automatically—every single day.**

## What Makes This Different

### 1. Smart Detection, Not Just Alerts
Most cost tools just notify you when you hit a threshold. This system uses **Median Absolute Deviation (MAD)** statistical analysis to understand *normal* vs *abnormal* spending patterns—even when your costs naturally vary day to day.
```python
# Traditional approach: "Alert if cost > $100"
if daily_cost > 100:
    alert()  # Too simplistic!

# This project: "Alert if cost is statistically anomalous"
z_score = 0.6745 * (cost - median) / mad
if abs(z_score) > 3.0:
    analyze_root_cause()  # Smart detection!
```

### 2. Root Cause Analysis Built-In
When an anomaly is detected, you don't just get "Your bill is high." You get:
- **Which AWS service** caused the spike (EC2, RDS, Lambda, etc.)
- **By how much** it increased (dollar amount + percentage)
- **Compared to what** (day-over-day analysis)
- **Ranked contributors** (top services sorted by impact)

### 3. 100% Serverless = Zero Maintenance
No servers to patch. No databases to manage. No monitoring tools to monitor. It just runs—daily, reliably, automatically.

### 4. Production-Grade Architecture
This isn't a toy project. It includes:
- Fault-tolerant error handling
- CloudWatch alarms for self-monitoring
- Encrypted S3 storage with lifecycle policies
- IAM least-privilege permissions
- Infrastructure as Code (CloudFormation)
- Automated scheduling with EventBridge

## Architecture
```
┌─────────────────────────────────────────────────────────────┐
│         EventBridge (Daily Trigger - cron schedule)         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Lambda Function                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 1. Fetch 30 days of cost data (Cost Explorer API)    │  │
│  │ 2. Calculate median and MAD for baseline             │  │
│  │ 3. Compute z-scores for each day                     │  │
│  │ 4. Flag anomalies (|z-score| > threshold)            │  │
│  │ 5. Perform root cause analysis (service breakdown)   │  │
│  │ 6. Send alerts + save reports                        │  │
│  └───────────────────────────────────────────────────────┘  │
└──────┬──────────────────┬─────────────────┬─────────────────┘
       │                  │                 │
       ▼                  ▼                 ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Cost        │   │ S3 Bucket   │   │     SNS     │
│ Explorer    │   │             │   │             │
│             │   │ • Reports   │   │ • Email     │
│ • Daily $   │   │ • History   │   │   alerts    │
│ • Per       │   │ • 90d       │   │ • Root      │
│   service   │   │   retention │   │   cause     │
└─────────────┘   └─────────────┘   └─────────────┘
```

## The Algorithm: Why MAD?

### The Problem with Standard Deviation
Most anomaly detection uses standard deviation, but it has a fatal flaw: **outliers skew the results**. If you have one massive spike, it raises the standard deviation, making future spikes harder to detect.

### The MAD Solution
**Median Absolute Deviation** is resistant to outliers. It calculates:

1. **Median** of all costs (instead of mean)
2. **Absolute deviations** from median
3. **Median** of those deviations (the MAD)
4. **Modified z-score**: `z = 0.6745 × (cost - median) / MAD`

**Why this works:**
- Median isn't affected by extreme values
- MAD provides a robust measure of variability
- Used in financial fraud detection and industrial quality control

### Real Example
```
Your daily AWS costs:
Day 1-25: $95-$110 (normal variation)
Day 26:   $487 (spike!)
Day 27-30: $98-$105 (back to normal)

Standard Deviation approach:
- Mean = $125
- Std Dev = $76 (inflated by the spike!)
- Day 26 z-score = 4.8
- Day 27 z-score = -0.4 (spike contaminated baseline)

MAD approach:
- Median = $102
- MAD = $5
- Day 26 z-score = 51.9 (clearly anomalous!)
- Day 27 z-score = -0.5 (clean baseline preserved)
```

**Result**: MAD correctly identifies the spike without letting it corrupt future analysis.

## Technical Implementation

### Core Detection Logic
```python
def detect_anomalies_mad(cost_data: List[Dict], threshold: float = 3.0) -> List[Dict]:
    """
    Detect cost anomalies using Median Absolute Deviation
    
    Args:
        cost_data: List of daily cost records
        threshold: Z-score threshold for anomaly detection
    
    Returns:
        List of detected anomalies with severity and root cause
    """
    costs = [day['total_cost'] for day in cost_data]
    
    # Calculate median (resistant to outliers)
    sorted_costs = sorted(costs)
    n = len(sorted_costs)
    median = sorted_costs[n // 2] if n % 2 == 1 else \
             (sorted_costs[n // 2 - 1] + sorted_costs[n // 2]) / 2
    
    # Calculate MAD
    absolute_deviations = [abs(cost - median) for cost in costs]
    sorted_deviations = sorted(absolute_deviations)
    mad = sorted_deviations[n // 2] if n % 2 == 1 else \
          (sorted_deviations[n // 2 - 1] + sorted_deviations[n // 2]) / 2
    
    if mad == 0:
        mad = 0.01  # Avoid division by zero
    
    # Calculate modified z-scores
    anomalies = []
    for day in cost_data:
        cost = day['total_cost']
        modified_z_score = 0.6745 * (cost - median) / mad
        
        if abs(modified_z_score) > threshold:
            anomaly_type = "spike" if modified_z_score > 0 else "drop"
            severity = "critical" if abs(modified_z_score) > threshold * 1.5 else "warning"
            
            anomalies.append({
                'date': day['date'],
                'cost': cost,
                'median': median,
                'z_score': modified_z_score,
                'anomaly_type': anomaly_type,
                'severity': severity,
                'services': day['services']
            })
    
    return sorted(anomalies, key=lambda x: abs(x['z_score']), reverse=True)
```

### Root Cause Analysis
```python
def perform_root_cause_analysis(anomaly: Dict) -> List[Dict]:
    """
    Identify which AWS services contributed to the anomaly
    Compares current day costs with previous day, service by service
    """
    services = anomaly['services']
    
    # Fetch previous day's data
    prev_date = datetime.strptime(anomaly['date'], '%Y-%m-%d') - timedelta(days=1)
    prev_data = fetch_cost_data_for_date(prev_date)
    
    # Calculate day-over-day changes
    analysis = []
    for service, current_cost in services.items():
        prev_cost = prev_data.get(service, 0)
        
        change_amount = current_cost - prev_cost
        change_percent = (change_amount / prev_cost * 100) if prev_cost > 0 else 100
        
        analysis.append({
            'service': service,
            'current_cost': current_cost,
            'previous_cost': prev_cost,
            'change_amount': change_amount,
            'change_percent': change_percent
        })
    
    # Return top contributors by absolute change
    return sorted(analysis, key=lambda x: abs(x['change_amount']), reverse=True)
```

## Technology Stack

**AWS Services:**
- **Lambda** - Serverless compute for detection logic
- **Cost Explorer API** - Historical cost data retrieval
- **EventBridge** - Automated daily scheduling
- **S3** - Persistent storage for analysis reports
- **SNS** - Email notifications with analysis results
- **CloudWatch** - Logging and alarm monitoring
- **IAM** - Least-privilege access control
- **CloudFormation** - Infrastructure as Code

**Languages & Tools:**
- **Python 3.11** - Core application logic
- **Boto3** - AWS SDK for Python
- **YAML** - Infrastructure definition

## Sample Alert
```
AWS Cost Anomaly Alert
============================================================

Date: 2025-01-06
Cost: $487.23
Expected (Median): $125.50
Deviation: $361.73 (+288.2%)
Z-Score: 5.42
Type: SPIKE
Severity: CRITICAL

Root Cause Analysis (Top Services):
------------------------------------------------------------
1. Amazon EC2: $325.00 (+450% vs prev day)
   Previous: $65.00, Change: +$260.00
   
2. Amazon RDS: $89.50 (+120% vs prev day)
   Previous: $40.70, Change: +$48.80
   
3. AWS Lambda: $42.73 (+15% vs prev day)
   Previous: $37.20, Change: +$5.53

Total Anomalies Detected: 1
Detection Time: 2025-01-06T12:00:00Z
```

## Cost Analysis

**Monthly Operating Cost: ~$0.30**

| Service | Usage | Monthly Cost |
|---------|-------|--------------|
| Lambda | 30 executions × 30s × 512MB | $0.00 (free tier) |
| Cost Explorer API | 30 API calls × $0.01 | $0.30 |
| S3 | <1 GB storage, 90 operations | $0.00 (free tier) |
| SNS | <100 emails | $0.00 (free tier) |
| EventBridge | 30 invocations | $0.00 (free tier) |
| CloudWatch | Logs + 2 alarms | $0.00 (free tier) |
| **Total** | | **$0.30/month** |

**ROI**: Detecting even one $100 cost spike pays for 333 months of operation.

## What This Demonstrates

### Technical Skills
- **Serverless Architecture**: Event-driven, auto-scaling design
- **Statistical Analysis**: MAD algorithm implementation
- **AWS Integration**: 7+ services working together
- **Infrastructure as Code**: Reproducible deployments
- **Production Practices**: Error handling, monitoring, security

### Problem-Solving Approach
- Identified a real problem (unexpected AWS bills)
- Researched robust solution (MAD vs standard deviation)
- Designed scalable architecture (serverless)
- Implemented production safeguards (alarms, encryption, IAM)
- Optimized for cost (leveraged free tier)

### FinOps Expertise
- Cost visibility and tracking
- Anomaly detection
- Root cause analysis
- Automated alerting
- Historical reporting

## Comparison to Commercial Solutions

| Feature | This Project | CloudHealth | Datadog | AWS Budgets |
|---------|-------------|-------------|---------|-------------|
| Cost | $0.30/month | $100+/month | $15+/month | Free |
| Anomaly Detection | MAD algorithm | Yes | Yes | Threshold only |
| Root Cause Analysis | Built-in | Yes | Yes | No |
| Automated Alerts | Yes | Yes | Yes | Yes |
| Historical Storage | 90 days | Unlimited | Varies | 12 months |
| Setup Time | 10 minutes | Hours | Hours | 5 minutes |
| Customizable | Fully | Limited | Limited | Limited |

## Future Enhancements

**Machine Learning Integration:**
- Replace MAD with Prophet or ARIMA for time-series forecasting
- Predict end-of-month costs based on current trends
- Seasonal adjustment for predictable spikes

**Multi-Account Support:**
- Deploy via CloudFormation StackSets
- Aggregate costs across AWS Organizations
- Consolidated anomaly detection

**Advanced Analytics:**
- Cost breakdown by resource tags
- Reserved Instance utilization tracking
- Savings recommendations based on usage patterns

**Integration Ecosystem:**
- Slack webhook notifications
- PagerDuty integration for critical alerts
- Datadog/Grafana metrics export
- JIRA ticket creation for anomalies

## Why This Matters for Production

This isn't just a demo project—it's production-ready code that could save companies thousands in unexpected cloud costs. The difference between getting a $5,000 surprise bill and catching a $200 spike before it becomes $5,000 is proactive monitoring with intelligent anomaly detection.

**Real-world impact:**
- Early detection of misconfigured resources
- Immediate alerting on security incidents (crypto mining)
- Visibility into cost trends before they escalate
- Automated reporting for FinOps teams

---

**Built with:** AWS Lambda | Python | CloudFormation | Statistical Analysis | FinOps Best Practices