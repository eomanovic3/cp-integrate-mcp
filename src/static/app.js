document.addEventListener("DOMContentLoaded", () => {
  const activitiesList = document.getElementById("activities-list");
  const activitySelect = document.getElementById("activity");
  const signupForm = document.getElementById("signup-form");
  const targetEmailGroup = document.getElementById("target-email-group");
  const targetEmail = document.getElementById("target-email");
  const loginForm = document.getElementById("login-form");
  const loginRequired = document.getElementById("login-required");
  const accountDetails = document.getElementById("account-details");
  const accountIdentity = document.getElementById("account-identity");
  const userCreateForm = document.getElementById("user-create-form");
  const messageDiv = document.getElementById("message");
  let currentUser = null;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => {
      const entities = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      };
      return entities[character];
    });
  }

  function showMessage(text, success) {
    messageDiv.textContent = text;
    messageDiv.className = success ? "success message" : "error message";
    messageDiv.classList.remove("hidden");
    setTimeout(() => messageDiv.classList.add("hidden"), 5000);
  }

  async function readResponse(response) {
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || "An error occurred");
    }
    return result;
  }

  function updateAuthUI() {
    const loggedIn = currentUser !== null;
    loginForm.classList.toggle("hidden", loggedIn);
    accountDetails.classList.toggle("hidden", !loggedIn);
    userCreateForm.classList.toggle(
      "hidden",
      !loggedIn || currentUser.role !== "teacher"
    );
    signupForm.classList.toggle("hidden", !loggedIn);
    loginRequired.classList.toggle("hidden", loggedIn);
    targetEmailGroup.classList.toggle(
      "hidden",
      !loggedIn || currentUser.role !== "teacher"
    );
    targetEmail.required = loggedIn && currentUser.role === "teacher";
    if (loggedIn) {
      accountIdentity.textContent = `${currentUser.email} (${currentUser.role.replace("_", " ")})`;
      document.getElementById("auth-status").textContent = "";
    }
  }

  async function fetchActivities() {
    try {
      const response = await fetch("/activities");
      const activities = await readResponse(response);
      activitiesList.innerHTML = "";
      activitySelect.innerHTML =
        '<option value="">-- Select an activity --</option>';

      Object.entries(activities).forEach(([name, details]) => {
        const activityCard = document.createElement("div");
        activityCard.className = "activity-card";
        const spotsLeft =
          details.max_participants - details.participants.length;
        const participantsHTML =
          details.participants.length > 0
            ? `<div class="participants-section">
              <h5>Participants:</h5>
              <ul class="participants-list">
                ${details.participants
                  .map((email) => {
                    const escapedEmail = escapeHtml(email);
                    const canUnregister =
                      currentUser &&
                      (currentUser.role === "teacher" ||
                        currentUser.email === email);
                    const removeButton = canUnregister
                      ? `<button class="delete-btn" data-activity="${escapeHtml(name)}" data-email="${escapedEmail}" aria-label="Unregister ${escapedEmail}">Remove</button>`
                      : "";
                    return `<li><span class="participant-email">${escapedEmail}</span>${removeButton}</li>`;
                  })
                  .join("")}
              </ul>
            </div>`
            : "<p><em>No participants yet</em></p>";

        activityCard.innerHTML = `
          <h4>${escapeHtml(name)}</h4>
          <p>${escapeHtml(details.description)}</p>
          <p><strong>Schedule:</strong> ${escapeHtml(details.schedule)}</p>
          <p><strong>Availability:</strong> ${spotsLeft} spots left</p>
          <div class="participants-container">${participantsHTML}</div>
        `;
        activitiesList.appendChild(activityCard);

        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        activitySelect.appendChild(option);
      });

      document.querySelectorAll(".delete-btn").forEach((button) => {
        button.addEventListener("click", handleUnregister);
      });
    } catch (error) {
      activitiesList.textContent =
        "Failed to load activities. Please try again later.";
      console.error("Error fetching activities:", error);
    }
  }

  async function handleUnregister(event) {
    const button = event.currentTarget;
    const activity = button.getAttribute("data-activity");
    const email = button.getAttribute("data-email");
    const query =
      currentUser.role === "teacher"
        ? `?email=${encodeURIComponent(email)}`
        : "";

    try {
      const response = await fetch(
        `/activities/${encodeURIComponent(activity)}/unregister${query}`,
        { method: "DELETE" }
      );
      const result = await readResponse(response);
      showMessage(result.message, true);
      await fetchActivities();
    } catch (error) {
      showMessage(error.message || "Failed to unregister. Please try again.", false);
      console.error("Error unregistering:", error);
    }
  }

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("login-email").value;
    const password = document.getElementById("login-password").value;

    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      currentUser = await readResponse(response);
      loginForm.reset();
      updateAuthUI();
      await fetchActivities();
    } catch (error) {
      showMessage(error.message || "Failed to log in. Please try again.", false);
    }
  });

  document.getElementById("logout-button").addEventListener("click", async () => {
    try {
      const response = await fetch("/auth/logout", { method: "POST" });
      await readResponse(response);
      currentUser = null;
      updateAuthUI();
      await fetchActivities();
      showMessage("Logged out", true);
    } catch (error) {
      showMessage(error.message || "Failed to log out. Please try again.", false);
    }
  });

  userCreateForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const newUser = {
      email: document.getElementById("new-user-email").value,
      password: document.getElementById("new-user-password").value,
      role: document.getElementById("new-user-role").value,
    };

    try {
      const response = await fetch("/auth/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newUser),
      });
      const result = await readResponse(response);
      userCreateForm.reset();
      showMessage(`Created ${result.role} account for ${result.email}`, true);
    } catch (error) {
      showMessage(error.message || "Failed to create account.", false);
    }
  });

  signupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const activity = activitySelect.value;
    const query =
      currentUser.role === "teacher"
        ? `?email=${encodeURIComponent(targetEmail.value)}`
        : "";

    try {
      const response = await fetch(
        `/activities/${encodeURIComponent(activity)}/signup${query}`,
        { method: "POST" }
      );
      const result = await readResponse(response);
      showMessage(result.message, true);
      signupForm.reset();
      await fetchActivities();
    } catch (error) {
      showMessage(error.message || "Failed to sign up. Please try again.", false);
    }
  });

  async function loadCurrentUser() {
    try {
      const response = await fetch("/auth/me");
      const result = await readResponse(response);
      currentUser = result.authenticated
        ? { email: result.email, role: result.role }
        : null;
      updateAuthUI();
    } catch (error) {
      document.getElementById("auth-status").textContent =
        "Unable to check your login status.";
      console.error("Error checking login status:", error);
    }
  }

  loadCurrentUser().then(fetchActivities);
});
