# Azure AI Foundry - Create Project

Azure AI Foundry requires you to create a **Project** before you can deploy models. Here's exactly what to enter:

---

## Step-by-Step: Create Project

### 1. When Foundry Opens (https://ai.azure.com/)

You'll see a prompt to **"Create a project"** or **"New project"**

Click **"+ New project"** or **"Create project"**

---

### 2. Fill in Project Details

Use these values:

| Field | Value to Enter |
|-------|----------------|
| **Project name** | `document-qa-project` |
| **Hub** | Select: **"Create new hub"** (if shown) |
| **Hub name** | `document-qa-hub` (if asked) |
| **Subscription** | Select your Azure subscription |
| **Resource group** | Select: **`rg-document-qa`** (or the one you created) |
| **Location/Region** | **East US** (same as your OpenAI resource) |
| **Connect Azure OpenAI** | Select: **`my-openai-service-atqor`** (your existing OpenAI resource) |
| **Connect AI Search** | Select: **`my-search-service-atqor`** (optional but recommended) |

---

## 📋 Quick Copy-Paste Values

```
Project name:          document-qa-project
Hub name:              document-qa-hub
Resource group:        rg-document-qa
Location:              East US
Azure OpenAI:          my-openai-service-atqor
AI Search:             my-search-service-atqor
```

---

## Important Notes

### ✅ **Connect Your Existing OpenAI Resource**
- When it asks **"Connect Azure OpenAI"** or **"Azure OpenAI Service"**
- **DO NOT** create a new one
- **SELECT** your existing resource: `my-openai-service-atqor`
- This connects your project to the OpenAI resource you already created

### ✅ **Use Same Region**
- Choose **East US** (same region as your OpenAI resource)
- This ensures everything is in the same location

### ✅ **Resource Group**
- Use the same resource group where your OpenAI service lives
- Probably: `rg-document-qa` or similar

---

## What if I Don't See These Options?

### Simplified Flow (No Hub Creation):
Some accounts show a simpler form:
- **Project name**: `document-qa-project`
- **Location**: East US
- Click **"Create"**

### Hub Already Exists:
If you see existing hubs:
- Select any existing hub in **East US** region
- Or create a new one with name: `document-qa-hub`

---

## After Project is Created

Once the project is created (takes 1-2 minutes):

### 1. Navigate to Deployments
- Look in the **left menu** for:
  - **"Deployments"** or
  - **"Models + endpoints"** → **"Deployments"** or
  - **"Shared resources"** → **"Deployments"**

### 2. Deploy Models
Click **"+ Deploy model"** or **"+ Create deployment"**

Then follow the main guide to deploy:
1. **gpt-4o-mini** with deployment name: `gpt-4o-mini`
2. **text-embedding-3-small** with deployment name: `text-embedding-3-small`

---

## Complete Flow Summary

```
Azure AI Foundry (ai.azure.com)
    ↓
Create Project
    - Name: document-qa-project
    - Region: East US
    - Connect: my-openai-service-atqor
    ↓
Project Created ✅
    ↓
Navigate to: Deployments
    ↓
Deploy Model 1: gpt-4o-mini
    ↓
Deploy Model 2: text-embedding-3-small
    ↓
Done! ✅
```

---

## Troubleshooting

### "Can't find my OpenAI resource to connect"
- Make sure you selected the correct **Subscription**
- Make sure you selected the correct **Resource Group**
- Make sure you selected **East US** region
- The resource must be in the same subscription to appear

### "Hub creation failed"
- Try using a different hub name (must be globally unique)
- Or select an existing hub if one is available

### "Don't see 'Connect Azure OpenAI' option"
- That's okay! The project might auto-detect it
- Proceed to create the project
- You'll be able to use your OpenAI resource after project creation

---

## What Are Projects and Hubs? (FYI)

- **Hub**: A container that groups related AI resources (OpenAI, Search, etc.)
- **Project**: A workspace within a hub where you deploy and manage models

Think of it like:
- **Hub** = Your office building
- **Project** = Your specific workspace/desk in that building

You need both to work in Azure AI Foundry, but once created, you can deploy models and use them normally.

---

## Next Steps After Project Creation

1. ✅ Project created
2. 👉 Go to **Deployments** section
3. 👉 Deploy **gpt-4o-mini** 
4. 👉 Deploy **text-embedding-3-small**
5. 👉 Run: `.venv\Scripts\python.exe check_deployments.py`
6. 🚀 Start the application!

---

Good luck! 🎯
