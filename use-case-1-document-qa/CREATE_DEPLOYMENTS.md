# Create Azure OpenAI Model Deployments

Your Azure OpenAI resource is created, but you need to **deploy the models** before the application can use them.

## Quick Steps

### 1. Open Azure AI Foundry Portal (formerly Azure OpenAI Studio)

**Method 1 - Direct Link:**
Go to: https://ai.azure.com/

**Method 2 - From Azure Portal:**
1. Go to https://portal.azure.com
2. Find your OpenAI resource: "my-openai-service-atqor"
3. Click the **"Go to Foundry portal"** button at the top (or "Explore in Azure AI Foundry")

**Note**: Azure rebranded "Azure OpenAI Studio" to "Azure AI Foundry Portal" in late 2024. It's the same service, just a new name!

### 2. Navigate to Your OpenAI Resource

1. Once in Azure AI Foundry Portal (https://ai.azure.com/), you might see a project/hub view
2. Look for **"All resources"** or **"Azure OpenAI"** in the left menu
3. Find and click on your resource: **"my-openai-service-atqor"**
4. Click **"Deployments"** in the left menu (or top menu)

### 3. Deploy GPT-4o-mini (Chat Model)

1. Click **"+ Deploy model"** or **"+ Create"** or **"Deploy base model"**
2. You'll see a list of available models
3. Find and select **"gpt-4o-mini"**:
   - If you don't see it, try **"gpt-4o"** instead (more expensive but works)
4. Click **"Confirm"** or **"Deploy"**
5. Fill in the deployment form:
   - **Deployment name**: Type exactly: `gpt-4o-mini`
   - **Model version**: Leave as default (or select latest)
   - **Deployment type**: Standard (or Global Standard if available)
   - **Tokens per Minute Rate Limit**: Leave default (e.g., 10K or 30K)
6. Click **"Deploy"** or **"Create"**
7. Wait 1-2 minutes for deployment to complete

### 4. Deploy text-embedding-3-small (Embedding Model)

1. Click **"+ Deploy model"** or **"+ Create"** again
2. Find and select **"text-embedding-3-small"**
3. Click **"Confirm"** or **"Deploy"**
4. Fill in the deployment form:
   - **Deployment name**: Type exactly: `text-embedding-3-small`
   - **Model version**: Leave as default
   - **Deployment type**: Standard (or Global Standard)
   - **Tokens per Minute Rate Limit**: Leave default
5. Click **"Deploy"** or **"Create"**
6. Wait 1-2 minutes for deployment to complete

### 5. Verify Deployments

After both deployments are created, you should see them in the Deployments list:

```
Deployment Name             Model                      Status
---------------------------------------------------------------
gpt-4o-mini                 gpt-4o-mini               Succeeded
text-embedding-3-small      text-embedding-3-small    Succeeded
```

**Note**: The Azure AI Foundry Portal interface may look slightly different depending on when you access it, but the core concept is the same: Deploy models → Give them names → Use those names in your code.

### 6. Test the Configuration

Back in your project folder, run:

```bash
.venv\Scripts\python.exe check_deployments.py
```

You should see:
```
✅ Chat deployment is working!
✅ Embedding deployment is working!
✅ All Azure OpenAI deployments are ready!
```

---

---

## 📸 Visual Guide - What to Look For

### In Azure Portal:
```
Your OpenAI Resource Page
├── Overview tab
├── [Go to Foundry portal] button  👈 CLICK THIS
└── or [Explore in Azure AI Foundry] button
```

### In Azure AI Foundry Portal (ai.azure.com):

**Layout Option 1 - Resource View:**
```
Left Menu:
├── All resources
├── Deployments  👈 CLICK HERE
├── Models
└── ...
```

**Layout Option 2 - Hub/Project View:**
```
Top Menu or Left Menu:
├── Shared resources
│   └── Deployments  👈 CLICK HERE
├── Models + endpoints
└── ...
```

**When Creating a Deployment:**
```
Deploy Model Dialog:
├── Select a model: [gpt-4o-mini ▼]  👈 CHOOSE MODEL
├── Deployment name: [gpt-4o-mini]   👈 TYPE NAME
├── Model version: [Latest ▼]
├── Deployment type: [Standard ▼]
└── [Deploy] button  👈 CLICK
```

---

## Troubleshooting

### "I don't see gpt-4o-mini in the model list"

**Option 1**: Use gpt-4o instead (more powerful but uses more credit)
- Deploy "gpt-4o" with deployment name: `gpt-4o`
- Update your `.env` file:
  ```
  AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
  ```

**Option 2**: Try a different region
- gpt-4o-mini might not be available in your region (East US)
- Create a new Azure OpenAI resource in a different region (e.g., Sweden Central, West US, West Europe have good availability)
- Update your `.env` file with the new endpoint and key

### "Quota exceeded" error

- Your region has limited quota for the free tier
- Options:
  1. Try deploying with a lower tokens-per-minute limit (e.g., 10K instead of 30K)
  2. Try a different region (Sweden Central often has better availability)
  3. Request quota increase in Azure AI Foundry Portal → Quotas section
  4. Try "Global Standard" deployment type if available (distributes load across regions)

### "Deployment takes too long"

- Deployments usually take 1-5 minutes
- If stuck for >10 minutes, delete and recreate the deployment
- Check Azure Service Health: https://status.azure.com/

---

## Important Notes

⚠️ **Deployment names MUST match your .env file exactly**
- The code looks for deployments by name
- If you use different names, update your `.env` file accordingly

⚠️ **Models vs Deployments**
- **Models** are the AI capabilities (gpt-4o-mini, text-embedding-3-small)
- **Deployments** are named instances you create (can be any name, but we use the model name for simplicity)
- One model can have multiple deployments with different names

---

## After Deployment

Once both deployments are created and the check passes, you can:

1. **Generate demo documents**:
   ```bash
   .venv\Scripts\python.exe scripts\make_samples.py
   ```

2. **Start the backend**:
   ```bash
   .venv\Scripts\python.exe -m uvicorn src.api.main:app --reload
   ```

3. **Start the frontend** (in a new terminal):
   ```bash
   .venv\Scripts\activate
   streamlit run frontend\app.py
   ```

4. **Open the app**: http://localhost:8501

Good luck! 🚀
