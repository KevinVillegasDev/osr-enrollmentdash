// Netlify Function: Proxy for triggering GitHub Actions workflow_dispatch
// Keeps the GitHub PAT server-side (set GITHUB_PAT in Netlify env vars)

exports.handler = async function (event) {
  // CORS headers for the dashboard
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
  };

  // Handle preflight
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers, body: "" };
  }

  if (event.httpMethod !== "POST") {
    return {
      statusCode: 405,
      headers,
      body: JSON.stringify({ success: false, message: "Method not allowed" }),
    };
  }

  const token = process.env.GITHUB_PAT || process.env.GH_PAT;
  if (!token) {
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ success: false, message: "GITHUB_PAT or GH_PAT not configured in Netlify env vars" }),
    };
  }

  const owner = "KevinVillegasDev";
  const repo = "osr-enrollmentdash";
  const workflowFile = "update-dashboards.yml";

  try {
    const response = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFile}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );

    if (response.status === 204) {
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          success: true,
          message: "Workflow triggered successfully",
        }),
      };
    }

    const errorText = await response.text();
    return {
      statusCode: response.status,
      headers,
      body: JSON.stringify({
        success: false,
        message: `GitHub API returned ${response.status}`,
        details: errorText,
      }),
    };
  } catch (err) {
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({
        success: false,
        message: "Failed to call GitHub API",
        details: err.message,
      }),
    };
  }
};
