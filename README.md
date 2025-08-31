# Code Review Bot

An automated AI-powered code review system that integrates with GitLab to provide intelligent code suggestions on merge requests. It uses AI models (Gemini or OpenAI) to analyze code diffs and post inline comments with improvement suggestions.

## Core Features

### 🤖 AI-Powered Code Review
- **Multi-Model Support**: Supports both Gemini (Google) and OpenAI models
- **Intelligent Analysis**: Reviews code diffs and identifies potential issues, improvements, and best practices
- **JSON-Structured Output**: Returns suggestions in structured format for precise inline commenting

### 🔗 GitLab Integration
- **Webhook Endpoint**: `/webhook` - Receives GitLab merge request events
- **Automatic Triggering**: Automatically processes MRs when they are created or updated
- **Inline Comments**: Posts suggestions directly as MR discussions at specific line numbers
- **Fallback Notes**: Posts summary notes when structured comments can't be parsed

### ⚡ Asynchronous Processing
- **Background Processing**: Uses threading to handle reviews without blocking webhook responses
- **Quick Response**: Returns 202 Accepted immediately, processes review in background
- **Non-blocking**: Webhook responds quickly to prevent GitLab timeouts

### 📊 Status Monitoring
- **Real-time Status**: `/status` endpoint provides current job status
- **Progress Tracking**: Shows files reviewed, comments posted, and any errors
- **Job History**: Tracks start/finish times and error details

### 🛡️ Error Handling & Resilience
- **Rate Limit Handling**: Detects and handles API rate limits gracefully
- **Model Fallback**: Automatically falls back to OpenAI if Gemini hits rate limits
- **Robust Error Recovery**: Continues processing other files even if one fails
- **Timeout Protection**: Uses reasonable timeouts for all API calls

## API Endpoints

### POST `/webhook`
**Purpose**: Receives GitLab webhook events for merge requests

**Request Body**: GitLab webhook payload
```json
{
  "object_kind": "merge_request",
  "project": {"id": 123},
  "object_attributes": {"iid": 456}
}
```

**Response**:
- `202 Accepted`: MR accepted for processing
- `400 Bad Request`: Invalid payload
- `200 OK`: Non-MR event (ignored)

### GET `/status`
**Purpose**: Returns current background job status

**Response**:
```json
{
  "status": "running|completed|error|idle",
  "started_at": "2024-01-01T12:00:00Z",
  "finished_at": "2024-01-01T12:05:00Z",
  "project_id": 123,
  "mr_iid": 456,
  "files_reviewed": 5,
  "comments_posted": 12,
  "errors": ["error1", "error2"]
}
```

## Configuration

### Environment Variables
```python
# GitLab Configuration
GITLAB_API = "https://gitlab.com/api/v4"
GITLAB_TOKEN = "your-gitlab-token"

# AI Model Configuration
MODEL_PROVIDER = "gemini|openai"
OPENAI_API_KEY = "your-openai-key"
GEMINI_API_KEY = "your-gemini-key"
OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-1.5-flash"
```

## Workflow

### 1. Webhook Reception
- GitLab sends webhook when MR is created/updated
- Bot validates payload and extracts MR details
- Returns 202 Accepted immediately

### 2. Background Processing
- Fetches MR changes and diff references from GitLab API
- Iterates through each changed file
- Calls AI model to review each file's diff

### 3. AI Review
- Formats diff with review prompt template
- Calls configured AI model (Gemini/OpenAI)
- Parses JSON response for suggestions

### 4. Comment Posting
- Posts inline comments at specific line numbers
- Falls back to summary notes if JSON parsing fails
- Tracks success/failure for status reporting

## AI Prompt Template
```
You are a senior reviewer. Review this Git diff from {file_path}.
Suggest issues in JSON format:
[{"line": <line_number>, "comment": "<suggestion>"}]
Diff:
{diff}
```

## Error Handling

### Rate Limits
- **Detection**: Checks for "429" or "ResourceExhausted" errors
- **Fallback**: Automatically switches to OpenAI if Gemini hits limits
- **Logging**: Detailed error messages for debugging

### API Failures
- **Timeout Protection**: 15-second timeouts on all external calls
- **Graceful Degradation**: Continues processing other files
- **Error Tracking**: Maintains error list in status endpoint

### JSON Parsing
- **Validation**: Attempts to parse AI responses as JSON
- **Fallback**: Posts as summary note if parsing fails
- **Logging**: Shows raw response for debugging

## Deployment

### Prerequisites
- GitLab instance (self-hosted or GitLab.com)
- OpenAI API key or Google Gemini API key
- GitLab personal access token with API permissions

### 1. Environment Configuration

Create a `config.py` file based on `example-config.py`:

```python
# GitLab Configuration
GITLAB_API = "https://gitlab.com/api/v4"  # or your self-hosted GitLab URL
GITLAB_TOKEN = "your-gitlab-personal-access-token"

# AI Model Configuration
MODEL_PROVIDER = "gemini"  # or "openai"
OPENAI_API_KEY = "your-openai-api-key"
GEMINI_API_KEY = "your-gemini-api-key"
OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-1.5-flash"
```

### 2. Docker Deployment (Recommended)

#### Build and Run
```bash
# Build the Docker image
docker build -t code-review-bot .

# Run the container
docker run -d \
  --name code-review-bot \
  -p 5001:5001 \
  -v $(pwd)/config.py:/app/config.py \
  code-review-bot

# Check if container is running
docker ps
docker logs code-review-bot
```

#### Using Docker Compose
Create `docker-compose.yml`:
```yaml
version: '3.8'
services:
  code-review-bot:
    build: .
    ports:
      - "5001:5001"
    volumes:
      - ./config.py:/app/config.py
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
```

Run with:
```bash
docker-compose up -d
```

### 3. Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python app/listener_review_bot.py

# The bot will be available at http://localhost:5001
```

### 4. GitLab Webhook Configuration

#### For GitLab.com:
1. Go to your project → Settings → Webhooks
2. Add new webhook:
   - **URL**: `https://your-domain.com/webhook` (or `http://localhost:5001/webhook` for local testing)
   - **Secret Token**: (optional) Add a secret for security
   - **Triggers**: Select "Merge request events"
   - **SSL Verification**: Enable for production

#### For Self-hosted GitLab:
1. Go to your project → Settings → Webhooks
2. Add new webhook:
   - **URL**: `http://your-bot-ip:5001/webhook`
   - **Triggers**: Select "Merge request events"

### 5. Production Deployment

#### Using Docker with Environment Variables
```bash
docker run -d \
  --name code-review-bot \
  -p 5001:5001 \
  -e GITLAB_API="https://gitlab.com/api/v4" \
  -e GITLAB_TOKEN="your-token" \
  -e MODEL_PROVIDER="gemini" \
  -e GEMINI_API_KEY="your-key" \
  -e OPENAI_API_KEY="your-key" \
  -e OPENAI_MODEL="gpt-4o-mini" \
  -e GEMINI_MODEL="gemini-1.5-flash" \
  code-review-bot
```

#### Using Reverse Proxy (Nginx)
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 6. Verification

#### Test the Webhook Endpoint
```bash
# Test if the bot is running
curl http://localhost:5001/status

# Expected response:
{
  "status": "idle",
  "started_at": null,
  "finished_at": null,
  "project_id": null,
  "mr_iid": null,
  "files_reviewed": 0,
  "comments_posted": 0,
  "errors": []
}
```

#### Test GitLab Integration
1. Create a test merge request in your GitLab project
2. Check the bot logs: `docker logs -f code-review-bot`
3. Verify comments appear in the MR

### 7. Troubleshooting

#### Common Issues

**Bot not responding to webhooks:**
```bash
# Check if container is running
docker ps

# Check logs
docker logs code-review-bot

# Test webhook endpoint
curl -X POST http://localhost:5001/webhook \
  -H "Content-Type: application/json" \
  -d '{"object_kind":"merge_request","project":{"id":123},"object_attributes":{"iid":456}}'
```

**Rate limit errors:**
- Check your API quota usage
- Consider upgrading to paid plans
- The bot will automatically fallback between providers

**Permission errors:**
- Ensure GitLab token has appropriate permissions (api, read_repository, write_repository)
- Verify the token is valid and not expired

**Container exits immediately:**
```bash
# Check container logs
docker logs code-review-bot

# Common causes:
# - Missing config.py file
# - Invalid API keys
# - Port already in use
```

#### Health Checks
```bash
# Check bot status
curl http://localhost:5001/status

# Monitor logs in real-time
docker logs -f code-review-bot

# Check resource usage
docker stats code-review-bot
```

### 8. Security Considerations

- **HTTPS**: Use HTTPS in production with proper SSL certificates
- **Webhook Secret**: Configure webhook secret tokens in GitLab
- **API Keys**: Store API keys securely (use environment variables or secrets management)
- **Network**: Restrict network access to the bot container
- **Updates**: Regularly update the bot and dependencies

## Monitoring & Debugging

### Logs
- **Job Progress**: Start/completion messages for each MR
- **Model Responses**: First 300 characters of AI responses
- **Error Details**: Full stack traces for debugging
- **Rate Limit Info**: Specific rate limit error messages

### Status Endpoint
- **Real-time Monitoring**: Check `/status` for current job state
- **Progress Tracking**: Files reviewed and comments posted
- **Error History**: List of errors encountered

## Limitations

### Rate Limits
- **Gemini Free Tier**: 50 requests per day
- **OpenAI**: Varies by plan and model
- **Mitigation**: Automatic fallback between providers

### File Size
- **Large Diffs**: May hit model token limits
- **Processing Time**: Large MRs take longer to process
- **Memory Usage**: Background threads consume memory

### GitLab API
- **Token Permissions**: Requires appropriate GitLab token permissions
- **Webhook Reliability**: Depends on GitLab webhook delivery
- **API Limits**: Subject to GitLab API rate limits

## Future Enhancements

### Planned Features
- **Queue System**: Replace threading with proper job queue (Redis/Celery)
- **Batch Processing**: Process multiple files in single API call
- **Custom Prompts**: Configurable review prompts per project
- **Filtering**: Skip certain file types or directories
- **Metrics**: Detailed performance and usage metrics

### Scalability
- **Horizontal Scaling**: Multiple worker instances
- **Load Balancing**: Distribute work across instances
- **Caching**: Cache common patterns and suggestions
- **Database**: Persistent job history and configuration

## Tech Stack
- **Python**: Core application language
- **Flask**: Web framework for webhook handling
- **OpenAI API**: GPT models for code review
- **Google Gemini API**: Alternative AI model
- **GitLab API**: Integration with GitLab MRs
- **Docker**: Containerized deployment
- **Threading**: Background job processing

## Quick Start
1. Install dependencies: `pip install -r requirements.txt`
2. Configure environment variables in `config.py`
3. Run the application: `python app/listener_review_bot.py`
4. Configure GitLab webhook to point to `/webhook` endpoint

