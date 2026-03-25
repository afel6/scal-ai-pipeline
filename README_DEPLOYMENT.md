# Deploying the SCAL AI Pipeline

To deploy your AI pipeline to the public internet (just like the Core Sample Selector), follow these 3 easy steps:

## Step 1: Push to GitHub
1. Open your terminal in this folder (`scal-ai-pipeline`).
2. Run `git init`.
3. Run `git add .` and `git commit -m "Initial commit"`.
4. Create a new repository on GitHub and push your code to it.

## Step 2: Deploy the Python Backend (Render.com)
1. Go to [Render.com](https://render.com) and sign in.
2. Click **New +** and select **Blueprint**.
3. Connect your GitHub account and select your `scal-ai-pipeline` repository.
4. Render will automatically detect the `render.yaml` file we created and deploy your FastAPI backend!
5. Once deployed, copy your backend URL (e.g., `https://scal-ai-backend.onrender.com`).

## Step 3: Deploy the React Frontend (Netlify.com)
1. Go to [Netlify.com](https://netlify.com) and log in.
2. Click **Add new site** -> **Import from an existing project**.
3. Select your GitHub repository.
4. Set the **Base directory** to `frontend`.
5. Click **Add environment variables** and add:
   - **Key:** `VITE_API_URL`
   - **Value:** *(Paste the exact Render URL from Step 2 here)*
6. Click **Deploy site**.

Once Netlify finishes building, you will have a permanent public URL for your SCAL AI Pipeline!
