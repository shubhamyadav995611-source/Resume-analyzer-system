
document.addEventListener("DOMContentLoaded", function () {

    console.log("Resume Analyzer JavaScript Loaded!");

    // ======================================
    // 1. RESUME ELEMENTS
    // ======================================

    const resumeInput = document.getElementById("resumeFile");
    const fileName = document.getElementById("fileName");
    const analyzeBtn = document.getElementById("analyzeBtn");
    const uploadMessage = document.getElementById("uploadMessage");

    // ======================================
    // 2. RESUME FILE SELECTION
    // ======================================

    if (resumeInput && analyzeBtn) {

        resumeInput.addEventListener("change", function () {

            const file = this.files[0];

            if (!file) {
                fileName.textContent = "Maximum file size: 5 MB";
                return;
            }

            const extension = file.name.split(".").pop().toLowerCase();

            if (!["pdf", "docx"].includes(extension)) {

                alert("Please upload only PDF or DOCX files.");

                this.value = "";
                fileName.textContent = "Maximum file size: 5 MB";

                return;
            }

            if (file.size > 5 * 1024 * 1024) {

                alert("File size should not exceed 5 MB.");

                this.value = "";
                fileName.textContent = "Maximum file size: 5 MB";

                return;
            }

            fileName.textContent = "Selected: " + file.name;

            if (uploadMessage) {
                uploadMessage.textContent = "";
            }

        });


        // ======================================
        // 3. ANALYZE RESUME BUTTON
        // ======================================

        analyzeBtn.addEventListener("click", async function (event) {

            event.preventDefault();

            const file = resumeInput.files[0];

            if (!file) {

                alert("Please select your resume first!");

                resumeInput.click();

                return;
            }

            const extension = file.name.split(".").pop().toLowerCase();

            if (!["pdf", "docx"].includes(extension)) {
                alert("Please select a PDF or DOCX file.");
                return;
            }

            if (file.size > 5 * 1024 * 1024) {
                alert("File size should not exceed 5 MB.");
                return;
            }

            const formData = new FormData();

            formData.append("resume", file);

            analyzeBtn.disabled = true;
            analyzeBtn.textContent = "Analyzing...";

            try {

                const response = await fetch("/analyze", {
                    method: "POST",
                    body: formData
                });

                const contentType =
                    response.headers.get("content-type") || "";

                if (!contentType.includes("application/json")) {
                    throw new Error("Invalid server response. Check Flask backend.");
                }

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || "Analysis failed.");
                }

                // ======================================
                // 4. DISPLAY MATCHING & MISSING SKILLS BOXES
                // ======================================

                const formatStat = (val) => {
                    const n = parseInt(val, 10);
                    if (isNaN(n)) return val;
                    return n < 10 ? "0" + n : n.toString();
                };

                // Update Top Statistics Cards from Backend
                if (result.total_resumes !== undefined) {
                    const totalEl = document.getElementById("totalResumes");
                    if (totalEl) totalEl.textContent = formatStat(result.total_resumes);
                }

                if (result.average_score !== undefined) {
                    const avgEl = document.getElementById("averageScore");
                    if (avgEl) avgEl.textContent = formatStat(result.average_score) + "%";
                }

                // Update Matching Skills and Missing Skills Small Boxes
                updateSkillsBreakdown(
                    result.filename,
                    result.job_title,
                    result.ats_score,
                    result.matched_skills,
                    result.missing_skills
                );

                // UPDATE RECENT ANALYSIS LIST DYNAMICALLY
                const historySection = document.getElementById("history");
                if (historySection) {
                    let historyList = historySection.querySelector(".history-list");
                    const emptyStateCard = historySection.querySelector(".history-card .empty-state");

                    if (emptyStateCard) {
                        const parentCard = emptyStateCard.closest(".history-card");
                        if (parentCard) parentCard.remove();
                    }

                    if (!historyList) {
                        historyList = document.createElement("div");
                        historyList.className = "history-list";
                        historySection.appendChild(historyList);
                    }

                    // Ensure Clear All button exists in heading
                    const headingDiv = historySection.querySelector(".section-heading");
                    if (headingDiv && !document.getElementById("clearAllHistoryBtn")) {
                        const clearBtn = document.createElement("button");
                        clearBtn.id = "clearAllHistoryBtn";
                        clearBtn.className = "clear-all-btn";
                        clearBtn.type = "button";
                        clearBtn.title = "Clear all analysis history";
                        clearBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i> Clear All';
                        headingDiv.appendChild(clearBtn);
                    }

                    const newHistoryCard = document.createElement("div");
                    newHistoryCard.className = "history-card active-history";
                    if (result.id) {
                        newHistoryCard.setAttribute("data-id", result.id);
                    }
                    newHistoryCard.setAttribute("data-filename", result.filename || "Resume");
                    newHistoryCard.setAttribute("data-job", result.job_title || "Job Profile");
                    newHistoryCard.setAttribute("data-score", result.ats_score || 0);
                    newHistoryCard.setAttribute("data-matched", JSON.stringify(result.matched_skills || []));
                    newHistoryCard.setAttribute("data-missing", JSON.stringify(result.missing_skills || []));

                    newHistoryCard.innerHTML = `
                        <div class="history-item-info">
                            <div class="stat-icon purple">
                                <i class="fa-solid fa-file-pdf"></i>
                            </div>
                            <div>
                                <h3>${result.filename}</h3>
                                <p>${result.job_title}</p>
                                <small>${result.created_at || 'Just now'}</small>
                            </div>
                        </div>
                        <div class="history-actions">
                            <div class="history-score">
                                <span>ATS Score</span>
                                <strong>${result.ats_score}%</strong>
                            </div>
                            <button type="button"
                                    class="view-history-btn"
                                    title="View matching & missing skills">
                                <i class="fa-solid fa-eye"></i> View Skills
                            </button>
                            <button type="button"
                                    class="delete-history-btn"
                                    data-id="${result.id || ''}"
                                    title="Delete this analysis">
                                <i class="fa-solid fa-trash-can"></i>
                            </button>
                        </div>
                    `;

                    // Remove previous active highlights
                    historySection.querySelectorAll(".history-card").forEach(function (c) {
                        c.classList.remove("active-history");
                    });

                    historyList.prepend(newHistoryCard);
                }


                // ======================================
                // 5. DYNAMIC COURSE RECOMMENDATIONS
                // ======================================

                displayCourses(result.recommended_courses || []);


                // ======================================
                // 6. SUCCESS MESSAGE & SCROLL
                // ======================================

                if (uploadMessage) {
                    uploadMessage.textContent =
                        "Resume analyzed successfully!";
                }

                const breakdownSec = document.getElementById("skillsBreakdownSection");
                if (breakdownSec) {
                    breakdownSec.scrollIntoView({
                        behavior: "smooth",
                        block: "center"
                    });
                }

                alert("Resume analysis completed successfully!");

            }

            catch (error) {

                console.error("Analysis Error:", error);

                alert("Error: " + error.message);

            }

            finally {

                analyzeBtn.disabled = false;

                analyzeBtn.textContent = "Analyze Resume →";

            }

        });

    }


    // ======================================
    // 7. COURSE DISPLAY FUNCTION
    // ======================================

    function displayCourses(courses) {

        const courseGrid = document.getElementById("courseGrid");

        if (!courseGrid) return;

        courseGrid.innerHTML = "";

        if (!courses.length) {

            courseGrid.innerHTML = `
                <div class="course-empty">
                    <i class="fa-solid fa-circle-check"></i>
                    <h3>No Missing Skills!</h3>
                    <p>Your resume matches all required skills.</p>
                </div>
            `;

            return;
        }

        courses.forEach(function (course) {

            const card = document.createElement("div");

            card.className = "course-card";

            const icon = document.createElement("div");

            icon.className = "course-icon purple";

            icon.innerHTML =
                '<i class="fa-solid fa-graduation-cap"></i>';

            const category = document.createElement("span");

            category.className = "course-category";

            category.textContent =
                "Missing Skill: " + course.skill;

            const title = document.createElement("h3");

            title.textContent = course.title;

            const description = document.createElement("p");

            description.textContent = course.description;

            const link = document.createElement("a");

            link.textContent = "Explore Course ";

            link.href = course.url;

            link.target = "_blank";

            link.rel = "noopener noreferrer";

            const linkIcon = document.createElement("i");

            linkIcon.className =
                "fa-solid fa-arrow-up-right-from-square";

            link.appendChild(linkIcon);

            card.append(
                icon,
                category,
                title,
                description,
                link
            );

            courseGrid.appendChild(card);

        });

    }


    // ======================================
    // 8. UPDATE MATCHING & MISSING SKILLS BOXES
    // ======================================

    function updateSkillsBreakdown(filename, jobTitle, atsScore, matchedSkills, missingSkills) {

        const breakdownSec = document.getElementById("skillsBreakdownSection");
        if (!breakdownSec) return;

        breakdownSec.style.display = "block";

        const meta = document.getElementById("breakdownMeta");
        if (meta) {
            meta.innerHTML =
                "Showing skills for <strong>" +
                (filename || "Uploaded Resume") +
                "</strong> (" +
                (jobTitle || "Job Profile") +
                ")";
        }

        const scoreVal = document.getElementById("breakdownScoreVal");
        if (scoreVal) {
            scoreVal.textContent = atsScore + "%";
        }

        const matchedBadge = document.getElementById("matchedCountBadge");
        if (matchedBadge) {
            matchedBadge.textContent =
                (matchedSkills ? matchedSkills.length : 0) + " Skills";
        }

        const missingBadge = document.getElementById("missingCountBadge");
        if (missingBadge) {
            missingBadge.textContent =
                (missingSkills ? missingSkills.length : 0) + " Skills";
        }

        const matchedList = document.getElementById("matchedSkillsList");
        if (matchedList) {
            matchedList.innerHTML = "";
            if (matchedSkills && matchedSkills.length > 0) {
                matchedSkills.forEach(function (skill) {
                    const tag = document.createElement("span");
                    tag.className = "skill-tag matched";
                    tag.innerHTML = '<i class="fa-solid fa-check"></i> ' + skill;
                    matchedList.appendChild(tag);
                });
            } else {
                matchedList.innerHTML =
                    '<span class="empty-skill-msg">No matching skills found for this resume.</span>';
            }
        }

        const missingList = document.getElementById("missingSkillsList");
        if (missingList) {
            missingList.innerHTML = "";
            if (missingSkills && missingSkills.length > 0) {
                missingSkills.forEach(function (skill) {
                    const tag = document.createElement("span");
                    tag.className = "skill-tag missing";
                    tag.innerHTML = '<i class="fa-solid fa-xmark"></i> ' + skill;
                    missingList.appendChild(tag);
                });
            } else {
                missingList.innerHTML =
                    '<span class="empty-skill-msg">No missing skills! 100% matched.</span>';
            }
        }

    }


    // ======================================
    // 9. JOB CRITERIA SAVE
    // ======================================

    const criteriaForm = document.getElementById("criteriaForm");

    if (criteriaForm) {

        criteriaForm.addEventListener("submit", async function (event) {

            event.preventDefault();

            const saveBtn =
                criteriaForm.querySelector(".save-btn");

            const saveMessage =
                document.getElementById("saveMessage");

            const formData = new FormData(criteriaForm);

            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.textContent = "Saving...";
            }

            try {

                const response = await fetch("/job-criteria", {
                    method: "POST",
                    body: formData
                });

                if (!response.ok) {
                    throw new Error("Unable to save job criteria.");
                }

                const html = await response.text();

                const parser = new DOMParser();

                const doc = parser.parseFromString(html, "text/html");

                const success = doc.getElementById("saveMessage");

                const error = doc.querySelector(".error-message");

                if (success) {

                    if (saveMessage) {
                        saveMessage.textContent =
                            success.textContent.trim();

                        saveMessage.style.color = "#22c55e";
                    }

                } else if (error) {

                    throw new Error(error.textContent.trim());

                } else {

                    throw new Error(
                        "Server did not return a confirmation message."
                    );

                }

            }

            catch (error) {

                console.error("Job Criteria Error:", error);

                if (saveMessage) {
                    saveMessage.textContent = error.message;
                    saveMessage.style.color = "#ff6b6b";
                } else {
                    alert(error.message);
                }

            }

            finally {

                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = "Save Job Criteria →";
                }

            }

        });

    }


    // ======================================
    // 10. LIVE STATISTICS SYNC
    // ======================================

    fetch("/api/stats")
        .then(function (response) {
            return response.json();
        })
        .then(function (data) {
            if (data && data.success) {
                const formatNum = function (val) {
                    const n = parseInt(val, 10);
                    if (isNaN(n)) return val;
                    return n < 10 ? "0" + n : n.toString();
                };

                const totalEl = document.getElementById("totalResumes");
                if (totalEl && data.total_resumes !== undefined) {
                    totalEl.textContent = formatNum(data.total_resumes);
                }

                const avgEl = document.getElementById("averageScore");
                if (avgEl && data.average_score !== undefined) {
                    avgEl.textContent = formatNum(data.average_score) + "%";
                }
            }
        })
        .catch(function (err) {
            console.warn("Could not sync live stats:", err);
        });


    // ======================================
    // 11. DELETE, CLEAR & VIEW HISTORY HANDLERS
    // ======================================

    const historySection = document.getElementById("history");

    if (historySection) {

        historySection.addEventListener("click", async function (event) {

            // Handle Single History Item Delete
            const deleteBtn = event.target.closest(".delete-history-btn");

            if (deleteBtn) {

                event.preventDefault();
                event.stopPropagation();

                const historyId = deleteBtn.getAttribute("data-id");

                if (!historyId) return;

                if (!confirm("Are you sure you want to delete this analysis?")) {
                    return;
                }

                deleteBtn.disabled = true;

                try {

                    const response = await fetch("/delete-history/" + historyId, {
                        method: "POST"
                    });

                    const data = await response.json();

                    if (!response.ok || !data.success) {
                        throw new Error(data.error || "Failed to delete record.");
                    }

                    const formatNum = function (val) {
                        const n = parseInt(val, 10);
                        if (isNaN(n)) return val;
                        return n < 10 ? "0" + n : n.toString();
                    };

                    const totalEl = document.getElementById("totalResumes");
                    if (totalEl && data.total_resumes !== undefined) {
                        totalEl.textContent = formatNum(data.total_resumes);
                    }

                    const avgEl = document.getElementById("averageScore");
                    if (avgEl && data.average_score !== undefined) {
                        avgEl.textContent = formatNum(data.average_score) + "%";
                    }

                    // Animate and remove the card
                    const card = deleteBtn.closest(".history-card");

                    if (card) {
                        card.style.transition = "all 0.3s ease";
                        card.style.opacity = "0";
                        card.style.transform = "translateX(25px)";

                        setTimeout(function () {
                            card.remove();

                            const remainingCards = historySection.querySelectorAll(
                                ".history-list .history-card"
                            );

                            if (remainingCards.length === 0) {
                                const historyList =
                                    historySection.querySelector(".history-list");
                                if (historyList) historyList.remove();

                                const clearBtn =
                                    document.getElementById("clearAllHistoryBtn");
                                if (clearBtn) clearBtn.remove();

                                const emptyCard = document.createElement("div");
                                emptyCard.className = "history-card";
                                emptyCard.innerHTML = `
                                    <div class="empty-state">
                                        <div class="empty-icon">
                                            <i class="fa-solid fa-clock-rotate-left"></i>
                                        </div>
                                        <h3>No Analysis Yet</h3>
                                        <p>Your resume analysis history will appear here after your first successful analysis.</p>
                                        <a href="#upload">Upload Your Resume →</a>
                                    </div>
                                `;
                                historySection.appendChild(emptyCard);
                            }
                        }, 300);
                    }

                } catch (error) {
                    console.error("Delete Error:", error);
                    alert(error.message);
                    deleteBtn.disabled = false;
                }

                return;
            }

            // Handle Clicking on a History Card or "View Skills" button
            const card = event.target.closest(".history-card");

            if (!card || card.querySelector(".empty-state")) return;

            // Highlight selected card
            historySection.querySelectorAll(".history-card").forEach(function (c) {
                c.classList.remove("active-history");
            });
            card.classList.add("active-history");

            const filename = card.getAttribute("data-filename") || "Resume";
            const job = card.getAttribute("data-job") || "Job Profile";
            const score = card.getAttribute("data-score") || "0";

            let matched = [];
            let missing = [];

            try {
                const matchedRaw = card.getAttribute("data-matched");
                matched = typeof matchedRaw === "string" ? JSON.parse(matchedRaw) : (matchedRaw || []);
            } catch (e) {
                matched = [];
            }

            try {
                const missingRaw = card.getAttribute("data-missing");
                missing = typeof missingRaw === "string" ? JSON.parse(missingRaw) : (missingRaw || []);
            } catch (e) {
                missing = [];
            }

            updateSkillsBreakdown(filename, job, score, matched, missing);

            const breakdownSec = document.getElementById("skillsBreakdownSection");
            if (breakdownSec) {
                breakdownSec.scrollIntoView({
                    behavior: "smooth",
                    block: "center"
                });
            }

        });

    }

    // Clear All History
    document.addEventListener("click", async function (event) {

        const clearBtn = event.target.closest("#clearAllHistoryBtn");

        if (!clearBtn) return;

        event.preventDefault();

        if (!confirm("Are you sure you want to delete ALL analysis history?")) {
            return;
        }

        clearBtn.disabled = true;
        clearBtn.textContent = "Clearing...";

        try {

            const response = await fetch("/clear-history", {
                method: "POST"
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.error || "Failed to clear history.");
            }

            const formatNum = function (val) {
                const n = parseInt(val, 10);
                if (isNaN(n)) return val;
                return n < 10 ? "0" + n : n.toString();
            };

            const totalEl = document.getElementById("totalResumes");
            if (totalEl) totalEl.textContent = formatNum(data.total_resumes);

            const avgEl = document.getElementById("averageScore");
            if (avgEl) avgEl.textContent = formatNum(data.average_score) + "%";

            const historySec = document.getElementById("history");

            if (historySec) {
                const historyList = historySec.querySelector(".history-list");
                if (historyList) historyList.remove();

                clearBtn.remove();

                const emptyCard = document.createElement("div");
                emptyCard.className = "history-card";
                emptyCard.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">
                            <i class="fa-solid fa-clock-rotate-left"></i>
                        </div>
                        <h3>No Analysis Yet</h3>
                        <p>Your resume analysis history will appear here after your first successful analysis.</p>
                        <a href="#upload">Upload Your Resume →</a>
                    </div>
                `;
                historySec.appendChild(emptyCard);
            }

        } catch (error) {
            console.error("Clear Error:", error);
            alert(error.message);
            clearBtn.disabled = false;
            clearBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i> Clear All';
        }

    });

});
