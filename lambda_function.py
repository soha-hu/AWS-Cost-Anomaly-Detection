"""
ALTERNATIVE: 100% FREE Cost Monitoring (No Cost Explorer API)
Uses CloudWatch Billing Metrics instead - less detailed but completely free

WARNING: This gives TOTAL cost only, not per-service breakdown
Cost Explorer version is recommended even with $0.01/call cost
"""

import json
import boto3
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')  # Billing metrics only in us-east-1
sns = boto3.client('sns')
s3 = boto3.client('s3')

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
S3_BUCKET = os.environ.get('S3_BUCKET')
LOOKBACK_DAYS = int(os.environ.get('LOOKBACK_DAYS', '30'))
ANOMALY_THRESHOLD = float(os.environ.get('ANOMALY_THRESHOLD', '3.0'))


def lambda_handler(event, context):
    """
    FREE alternative using CloudWatch Billing Metrics
    NOTE: Requires billing metrics to be enabled in AWS Console
    """
    try:
        print(f"Starting FREE cost monitoring at {datetime.utcnow()}")
        
        # Fetch billing data from CloudWatch (FREE)
        cost_data = fetch_billing_metrics(LOOKBACK_DAYS)
        
        if not cost_data:
            return create_response(200, "No billing data available. Enable detailed billing in AWS Console.")
        
        # Detect anomalies
        anomalies = detect_anomalies_mad(cost_data, ANOMALY_THRESHOLD)
        
        # Save results
        save_to_s3(cost_data, anomalies)
        
        # Send alerts if needed
        if anomalies:
            send_alert(anomalies)
        
        result = {
            'timestamp': datetime.utcnow().isoformat(),
            'total_days_analyzed': len(cost_data),
            'anomalies_detected': len(anomalies),
            'note': 'Using FREE CloudWatch Billing Metrics (total cost only)'
        }
        
        print(f"Completed. Found {len(anomalies)} anomalies")
        return create_response(200, "Success", result)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return create_response(500, f"Error: {str(e)}")


def fetch_billing_metrics(lookback_days: int) -> List[Dict]:
    """
    Fetch billing metrics from CloudWatch (100% FREE)
    
    IMPORTANT: Enable in AWS Console:
    Billing → Billing Preferences → Receive Billing Alerts (checkbox)
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=lookback_days)
    
    print(f"Fetching FREE billing metrics from {start_time} to {end_time}")
    
    try:
        response = cloudwatch.get_metric_statistics(
            Namespace='AWS/Billing',
            MetricName='EstimatedCharges',
            Dimensions=[
                {'Name': 'Currency', 'Value': 'USD'}
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,  # 1 day
            Statistics=['Maximum']
        )
        
        # Sort by timestamp
        datapoints = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])
        
        # Convert to our format
        cost_data = []
        for i, point in enumerate(datapoints):
            # Calculate daily cost (difference from previous day)
            if i > 0:
                daily_cost = point['Maximum'] - datapoints[i-1]['Maximum']
            else:
                daily_cost = point['Maximum']  # First day is total
            
            cost_data.append({
                'date': point['Timestamp'].strftime('%Y-%m-%d'),
                'total_cost': round(max(daily_cost, 0), 2),  # Ensure non-negative
                'cumulative_cost': round(point['Maximum'], 2),
                'note': 'Total AWS cost only (no service breakdown in free version)'
            })
        
        print(f"Retrieved {len(cost_data)} days of FREE billing data")
        return cost_data
        
    except Exception as e:
        print(f"Error fetching billing metrics: {str(e)}")
        print("Make sure 'Receive Billing Alerts' is enabled in AWS Console → Billing Preferences")
        raise


def detect_anomalies_mad(cost_data: List[Dict], threshold: float) -> List[Dict]:
    """Same MAD algorithm as paid version"""
    if len(cost_data) < 7:
        return []
    
    costs = [day['total_cost'] for day in cost_data]
    
    # Calculate median
    sorted_costs = sorted(costs)
    n = len(sorted_costs)
    median = sorted_costs[n // 2] if n % 2 == 1 else (sorted_costs[n // 2 - 1] + sorted_costs[n // 2]) / 2
    
    # Calculate MAD
    absolute_deviations = [abs(cost - median) for cost in costs]
    sorted_deviations = sorted(absolute_deviations)
    mad = sorted_deviations[n // 2] if n % 2 == 1 else (sorted_deviations[n // 2 - 1] + sorted_deviations[n // 2]) / 2
    
    if mad == 0:
        mad = 0.01
    
    # Find anomalies
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
                'median': round(median, 2),
                'z_score': round(modified_z_score, 2),
                'anomaly_type': anomaly_type,
                'severity': severity,
                'deviation_amount': round(cost - median, 2),
                'deviation_percent': round(((cost - median) / median * 100), 2) if median > 0 else 0,
                'note': 'Use Cost Explorer version for service-level breakdown'
            })
    
    anomalies.sort(key=lambda x: abs(x['z_score']), reverse=True)
    return anomalies


def send_alert(anomalies: List[Dict]):
    """Send SNS alert"""
    if not SNS_TOPIC_ARN:
        return
    
    anomaly = anomalies[0]
    
    subject = f"🚨 AWS Cost Anomaly - {anomaly['severity'].upper()}"
    
    message = f"""
AWS Cost Anomaly Alert (FREE CloudWatch Version)
{'=' * 60}

📅 Date: {anomaly['date']}
💰 Daily Cost: ${anomaly['cost']:,.2f}
📊 Expected (Median): ${anomaly['median']:,.2f}
📈 Deviation: ${anomaly['deviation_amount']:,.2f} ({anomaly['deviation_percent']:+.1f}%)
⚡ Z-Score: {anomaly['z_score']:.2f}
🔔 Type: {anomaly['anomaly_type'].upper()}

⚠️  NOTE: This is the FREE version using CloudWatch Billing Metrics
    For service-level breakdown, use the Cost Explorer version ($0.01/run)

Total Anomalies Detected: {len(anomalies)}
Detection Time: {datetime.utcnow().isoformat()}
"""
    
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message
        )
        print(f"Alert sent to SNS")
    except Exception as e:
        print(f"Error sending alert: {str(e)}")


def save_to_s3(cost_data: List[Dict], anomalies: List[Dict]):
    """Save to S3"""
    if not S3_BUCKET:
        return
    
    timestamp = datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')
    
    result = {
        'timestamp': datetime.utcnow().isoformat(),
        'version': 'FREE - CloudWatch Billing Metrics',
        'cost_data': cost_data,
        'anomalies': anomalies,
        'note': 'For service-level analysis, upgrade to Cost Explorer version'
    }
    
    try:
        key = f"cost-anomaly-reports/{timestamp}.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(result, indent=2),
            ContentType='application/json'
        )
        print(f"Results saved to s3://{S3_BUCKET}/{key}")
    except Exception as e:
        print(f"Error saving to S3: {str(e)}")


def create_response(status_code: int, message: str, data: Optional[Dict] = None) -> Dict:
    """Create response"""
    return {
        'statusCode': status_code,
        'body': json.dumps({
            'message': message,
            'data': data
        })
    }


"""
SETUP INSTRUCTIONS FOR FREE VERSION:

1. Enable billing metrics in AWS Console:
   - Go to Billing → Billing Preferences
   - Check "Receive Billing Alerts"
   - Wait ~6 hours for first metrics

2. Deploy with this code instead of lambda_function.py:
   - Replace lambda_function.py with this file
   - Run ./deploy.sh
   - Choose "Manual only" mode (completely free)

3. Run manually:
   - ./trigger.sh (100% FREE - no Cost Explorer API calls)

LIMITATIONS:
- Total cost only (no per-service breakdown)
- Updated every 6 hours (not real-time)
- Less granular than Cost Explorer
- Historical data limited to what CloudWatch stores

RECOMMENDATION:
The Cost Explorer version ($0.01/call) is better because:
- Service-level breakdown (know which service spiked)
- More accurate data
- Better root cause analysis
- Industry standard approach
- Cost is minimal ($0.30/month for daily, or $0.01 for manual)

But if you absolutely need $0 cost, this works!
"""
