Tracing for Strands Agents
This project demonstrates how to instrument and trace an example strands agent to LangSmith using OpenTelemetry, enabling you to monitor model & agent performance, latency, and token usage.

🛠 Setup
Clone the repo

### Clone the repo
```
git clone https://github.com/catherine-langchain/strands-example
```

### Create an environment variables file
```
$ cd strands-example
# Copy the .env.example file to .env
cp .env.example .env
```
Fill in fields such as OTel endpoint, headers (project and API key), and AWS credentials

### Package Installation
Ensure you have a recent version of pip and python installed
```
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install -r requirements.txt
```
### Run the agent 
Ensure you have a recent version of pip and python installed
```
$ python3 otel_strands_share.py
```

You can then see an example [trace](https://smith.langchain.com/public/84247784-e832-423d-8afa-50c5de9ca3ae/r) in the LangSmith project specified! 
