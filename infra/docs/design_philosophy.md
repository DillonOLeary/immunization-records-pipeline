# Design Philosophy: Minnesota Immunization Infrastructure

## Vision: Brilliant Simplicity for Statewide Impact

This infrastructure is designed for **statewide deployment** across Minnesota school districts. The core principle is "brilliant simplicity" - maximum reliability and security with minimum complexity.

## Architecture Overview

```mermaid
graph TB
    A[Cloud Scheduler<br/>Monday 9am] -->|Triggers| B[Pub/Sub Topic]
    B --> C[Upload Function]
    C -->|Uploads data to| D[AISR System]
    
    E[Cloud Scheduler<br/>Wednesday 9am] -->|Triggers| F[Pub/Sub Topic]
    F --> G[Download Function]
    G -->|Downloads from| D
    G -->|Transforms & stores| H[Storage Bucket<br/>HIPAA Compliant]
    
    I[Service Account] -.->|Secure access| C
    I -.->|Secure access| G
    J[Secret Manager] -.->|AISR credentials| C
    J -.->|AISR credentials| G
    
    style H fill:#e1f5fe
    style D fill:#fff3e0
    style I fill:#f3e5f5
    style J fill:#e8f5e8
```

## Design Principles

### 1. **Statewide Scalability**

**Problem:** Each of Minnesota's 500+ school districts needs immunization processing  
**Solution:** One codebase, infinite deployments

```mermaid
graph LR
    A[Single Repository] --> B[District A<br/>Project: mn-immun-districtA]
    A --> C[District B<br/>Project: mn-immun-districtB]
    A --> D[District C<br/>Project: mn-immun-districtC]
    A --> E[... 500+ districts]
    
    style A fill:#e3f2fd
```

Each district runs:
```bash
git clone minnesota-immunization-infra
cd minnesota-immunization-infra
# Change only project_id in terraform.tfvars
terraform apply
```

### 2. **Event-Driven Architecture**

**Why:** Reliability + Cost Efficiency + Zero Maintenance

```mermaid
sequenceDiagram
    participant S as Cloud Scheduler
    participant P as Pub/Sub
    participant F as Cloud Function
    participant A as AISR System
    participant B as Storage Bucket
    
    Note over S,B: Monday: Upload Phase
    S->>P: Trigger (Monday 9am)
    P->>F: Invoke Upload Function
    F->>A: Upload student data
    
    Note over S,B: Wednesday: Download Phase  
    S->>P: Trigger (Wednesday 9am)
    P->>F: Invoke Download Function
    F->>A: Download vaccination records
    F->>B: Store transformed CSV files
```

**Benefits:**
- Functions only run when needed (cost: ~$2/month per district)
- Google's Pub/Sub has 99.95% uptime SLA
- Automatic retries on failure
- No servers to maintain

### 3. **Security by Design (HIPAA Compliant)**

**Student health data requires maximum protection:**

```mermaid
graph TB
    subgraph "Security Layers"
        A[Google-Managed Encryption<br/>at Rest]
        B[Service Account<br/>Least Privilege]
        C[Secret Manager<br/>Credential Storage]
        D[Uniform Bucket Access<br/>No Public Access]
        E[3-Year Retention<br/>HIPAA Compliance]
    end
    
    F[Student Health Data] --> A
    A --> B
    B --> C
    C --> D
    D --> E
    
    style F fill:#ffebee
    style A fill:#e8f5e8
    style B fill:#e8f5e8
    style C fill:#e8f5e8
    style D fill:#e8f5e8
    style E fill:#e8f5e8
```

**Security Features:**
- **Encryption**: Google-managed keys (HIPAA compliant by default)
- **Access Control**: Service accounts with minimal permissions
- **Credential Management**: Secrets stored in Google Secret Manager
- **Data Lifecycle**: Automatic 3-year retention and deletion
- **Versioning**: File versioning for data integrity

### 4. **Operational Simplicity**

**Problem:** School IT staff have limited time and resources  
**Solution:** Zero-maintenance infrastructure

```mermaid
graph LR
    A[Deploy Once] --> B[Runs Automatically]
    B --> C[Monday: Upload]
    C --> D[Wednesday: Download]
    D --> B
    
    E[Manual Intervention] -.->|Only if needed| F[View Logs in Console]
    E -.->|Emergency| G[Manual Function Trigger]
    
    style A fill:#e8f5e8
    style B fill:#e1f5fe
    style C fill:#fff3e0
    style D fill:#fff3e0
```

**Operational Benefits:**
- Fully automated weekly cycle
- Cloud monitoring and alerting
- Detailed logs for troubleshooting
- Manual override capabilities

## Technology Choices

### Why Google Cloud Functions (Gen 2)?

1. **Serverless**: No infrastructure to manage
2. **Auto-scaling**: Handles load spikes during enrollment periods
3. **Pay-per-use**: Cost-effective for periodic workloads
4. **Python 3.11**: Modern runtime with excellent library support

### Why Terraform?

1. **Infrastructure as Code**: Version controlled, peer-reviewable
2. **Reproducible**: Same infrastructure across all districts
3. **Open Source**: No vendor lock-in
4. **Community**: Large ecosystem and support

### Why Event-Driven (Pub/Sub + Scheduler)?

1. **Reliability**: Pub/Sub has enterprise-grade SLAs
2. **Decoupling**: Components can be updated independently
3. **Monitoring**: Built-in observability and alerting
4. **Retry Logic**: Automatic handling of transient failures

## Cost Analysis

### Per District Monthly Cost (Estimated)

```mermaid
pie title Monthly Cost Breakdown (~$2/district)
    "Cloud Functions" : 60
    "Cloud Storage" : 25
    "Pub/Sub" : 10
    "Secret Manager" : 5
```

- **Cloud Functions**: ~$1.20/month (2 executions/week, 5min each)
- **Cloud Storage**: ~$0.50/month (assuming <100MB data)
- **Pub/Sub**: ~$0.20/month (8 messages/month)
- **Secret Manager**: ~$0.10/month (2 secrets)

**Total: ~$2/month per district**

### Statewide Impact
- 500 districts × $2/month = $1,000/month statewide
- Compare to: Single proprietary solution at $50,000+/year
- **Cost savings: 83%+ vs commercial alternatives**

## Deployment Strategy

### Phase 1: Pilot Districts (2-3 districts)
```mermaid
graph LR
    A[Select Pilot Districts] --> B[Deploy Infrastructure]
    B --> C[Test Full Cycle]
    C --> D[Gather Feedback]
    D --> E[Refine Process]
```

### Phase 2: Regional Rollout (10-20 districts)
```mermaid
graph LR
    A[Regional Deployment] --> B[Training Materials]
    B --> C[Support Documentation]
    C --> D[Monitor Operations]
```

### Phase 3: Statewide (All districts)
```mermaid
graph LR
    A[Self-Service Deployment] --> B[Community Support]
    B --> C[Continuous Improvement]
```

## Why This Will Work Across Minnesota

### Technical Reasons
- **Standardized**: Same AISR system statewide
- **Isolated**: Each district gets separate Google Cloud project
- **Scalable**: Architecture handles 1 district or 1,000 districts
- **Maintainable**: Single codebase for all deployments

### Practical Reasons
- **Budget-Friendly**: $24/year per district vs thousands for commercial solutions
- **Open Source**: Districts can customize for their needs
- **No Vendor Lock-in**: Built on open standards
- **Community-Driven**: Districts can contribute improvements

### Success Metrics
- **Reliability**: >99% successful data transfers
- **Cost**: <$50/district/year (vs $500+ for alternatives)
- **Adoption**: >50% of districts using within 2 years
- **Contribution**: >5 districts contributing code improvements

## Future Enhancements

### Phase 1 Improvements
```mermaid
graph TB
    A[Current System] --> B[Enhanced Monitoring]
    A --> C[Slack/Email Alerts]
    A --> D[Dashboard UI]
    A --> E[Batch Processing]
```

### Phase 2 Possibilities
- Real-time sync option
- Multi-state compatibility
- Integration with other school systems
- Machine learning for data quality

---

*This design prioritizes reliability, security, and simplicity over complexity. Every architectural decision serves the ultimate goal: ensuring Minnesota students can attend school without immunization record barriers.*