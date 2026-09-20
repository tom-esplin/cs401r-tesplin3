## ADR-001: NorthStar Platform Foundation

### Status

Accepted

### Context

NorthStar is interested in developing AI systems that enable it to be able to regain 140 million dollars a year due to inactive customers. So therefore it is spearheading a three pillar AI strategy to  increase customer retention. This includes a churn prediction model, to identify at risk customers, a generative offer systems to give customers personalized offers and finally a customer service agent to help out said customers. The infrastructure will be built out on AWS for best scaling. We will use a platform since this is the best way to deploy and monitor all three service simultaneously. 

### Decision
We used a VPC with a subnet because it is critical to isolate our services from the public web. We use IAM roles to follow the principle of least privilege. Additionally, we decided to use SageMaker AI versus using dedicated EC2 instance for ML which probably is more expensive. 
### Consequences

#### What this makes easy
Having our whole stack on AWS makes managing it a lot easier, using terraform and the console. We can quickly deploy and teardown as well as manage resources using AWS tools. Billing is easily accessible in the console as well which is convenient for other purposes.
#### What this makes harder
This makes it harder to save money as alternatives such as self hosting allow us to fine tune what we want to spend money on.
#### What would cause you to revisit this decision
If I found we didn't need most of the feature in SageMaker AI I would consider changing to a more local based solution.
### Alternative Considered
Since most of the AI would not need to scale extremely, especially the ML model we could run all the ML solutions on our own hardware. However, I would reject this because generative AI is hard to do locally as cost effectively while maintaining high performance

### AWS Service Selection

* Networking isolation model
Our network isolation Model is a simple VPC with an intertnet gateway since that is the easiest and cheapest way to do so.
* Storage design
We use S3 for simplicity, one bucket with multiple prefixes to lower possible data egress cost(keeping as much moving within the bucket as possible).
* Identity model
We use IAM with ML Role to best help manage our ML Engineers, having them focus on building the models in SageMaker rather than dealing with the whole architecture stack.
* ML development environment
We use SageMaker AI since it is the easiest to get off the ground and start doing ML but it is rather expensive for notebook work.

