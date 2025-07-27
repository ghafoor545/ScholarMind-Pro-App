import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
import google.generativeai as genai
from dotenv import load_dotenv
import os
import time
import sqlite3
from passlib.hash import pbkdf2_sha256
import uuid

# Load environment variables
load_dotenv()


# Database setup
def init_db():
    conn = sqlite3.connect('scholarmind.db')
    c = conn.cursor()

    # Create users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Create research_history table
    c.execute('''CREATE TABLE IF NOT EXISTS research_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  topic TEXT NOT NULL,
                  content_type TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')

    # Create admin user if none exists
    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if c.fetchone()[0] == 0:
        admin_hash = pbkdf2_sha256.hash("admin123")
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                  ("admin", admin_hash, "admin"))

    conn.commit()
    conn.close()


init_db()


# Database functions
def authenticate_user(username, password):
    conn = sqlite3.connect('scholarmind.db')
    c = conn.cursor()
    c.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()

    if user and pbkdf2_sha256.verify(password, user[2]):
        return {
            'id': user[0],
            'username': user[1],
            'role': user[3],
            'is_admin': user[3] == 'admin'
        }
    return None


def add_user(username, password, role="user"):
    try:
        conn = sqlite3.connect('scholarmind.db')
        c = conn.cursor()
        password_hash = pbkdf2_sha256.hash(password)
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                  (username, password_hash, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def save_research_history(user_id, topic, content_type, content):
    conn = sqlite3.connect('scholarmind.db')
    c = conn.cursor()
    c.execute("INSERT INTO research_history (user_id, topic, content_type, content) VALUES (?, ?, ?, ?)",
              (user_id, topic, content_type, content))
    conn.commit()
    conn.close()


def get_research_history(user_id):
    conn = sqlite3.connect('scholarmind.db')
    c = conn.cursor()
    c.execute("""
        SELECT id, topic, content_type, created_at 
        FROM research_history 
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (user_id,))
    history = c.fetchall()
    conn.close()
    return history


def get_research_content(history_id):
    conn = sqlite3.connect('scholarmind.db')
    c = conn.cursor()
    c.execute("SELECT content FROM research_history WHERE id = ?", (history_id,))
    content = c.fetchone()
    conn.close()
    return content[0] if content else None


# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Set page config with attractive settings
st.set_page_config(
    page_title="ScholarMind Pro",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://example.com/help',
        'Report a bug': 'https://example.com/bug',
        'About': "# ScholarMind Pro - AI Research Assistant"
    }
)


# Custom CSS
def local_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning("styles.css file not found. Using default styling.")


local_css("styles.css")


# Initialize session state
def get_trending_topics():
    prompt = """Generate exactly 5 trending academic research topics with brief descriptions.
    Format as:
    1. Topic: Description (max 20 words)
    2. Topic: Description (max 20 words)
    3. Topic: Description (max 20 words)
    4. Topic: Description (max 20 words)
    5. Topic: Description (max 20 words)
    Return only the numbered list, nothing else."""
    for attempt in range(3):  # Retry up to 3 times
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            topics = [line.split(": ", 1)[1].strip() for line in response.text.split("\n")
                      if ": " in line and line.strip()]
            if len(topics) >= 5:
                return topics[:5]  # Ensure exactly 5 topics
            time.sleep(1)
        except Exception as e:
            st.error(f"Attempt {attempt + 1} failed: {str(e)}")
            time.sleep(1)
    return [
        "AI Ethics: Ethical implications of AI in decision-making",
        "Quantum Computing: Advances in quantum algorithms",
        "Climate Modeling: Improved climate change predictions",
        "Bioinformatics: Genomic data analysis techniques",
        "Renewable Energy: Next-generation solar cell technology"
    ]


def init_session_state():
    defaults = {
        'authenticated': False,
        'is_admin': False,
        'current_page': "home",
        'final_topic': None,
        'topic_stage': "selecting",
        'trending_topics': [],
        'selected_trending': None,
        'subtopics': [],
        'subtopic_round': 1,
        'show_subtopic_section': False,
        'show_signup': False,
        'username': None,
        'user_id': None
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()

# Gemini model with error handling
try:
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"Failed to initialize Gemini model: {str(e)}")
    st.stop()


# Content generation functions
def generate_research_content(topic, content_type):
    prompts = {
        "questions": f"""Suggest 3 research questions on: '{topic}'
        Format as markdown bullet points""",
        "literature": f"""Write a detailed literature review (400-500 words) on: "{topic}".
        Include 5 relevant papers with summaries, overall findings, and research gaps.
        Use markdown formatting with headings and bullet points.""",
        "future": f"""List 5 future research directions for: '{topic}' 
        Format as markdown bullet points""",
        "references": f"""Provide 5 APA-style references for papers related to: '{topic}'
        Format as numbered list""",
        "abstract": f"""Write a formal academic abstract (150-200 words) for: '{topic}'
        Use professional academic language""",
        "analysis": f"""Generate exactly 5 sub-topics related to: '{topic}'.
        Format as:
        1. Sub-topic description
        2. Sub-topic description
        3. Sub-topic description
        4. Sub-topic description
        5. Sub-topic description
        Return only the numbered list, nothing else."""
    }
    for attempt in range(3):  # Retry up to 3 times
        try:
            response = model.generate_content(prompts[content_type])
            content = response.text
            if content_type == "analysis":
                subtopics = [line.split(". ", 1)[1].strip() for line in content.split("\n")
                             if line.strip() and line.strip()[0].isdigit() and ". " in line]
                if len(subtopics) >= 5:
                    if st.session_state.authenticated:
                        save_research_history(
                            st.session_state.user_id,
                            topic,
                            content_type,
                            content
                        )
                    return "\n".join([f"{i + 1}. {subtopics[i]}" for i in range(5)])
            if st.session_state.authenticated:
                save_research_history(
                    st.session_state.user_id,
                    topic,
                    content_type,
                    content
                )
            return content
        except Exception as e:
            st.error(f"Attempt {attempt + 1} failed for {content_type}: {str(e)}")
            time.sleep(1)
    if content_type == "analysis":
        return "\n".join([
            "1. Sample sub-topic 1",
            "2. Sample sub-topic 2",
            "3. Sample sub-topic 3",
            "4. Sample sub-topic 4",
            "5. Sample sub-topic 5"
        ])
    return f"Could not generate {content_type} content. Please try again."


# Authentication components
def show_auth():
    st.title("ScholarMind Pro 🧠")
    st.markdown("---")

    if st.session_state.show_signup:
        show_signup()
    else:
        show_login()


def show_login():
    col1, col2 = st.columns(2)

    with col1:
        with st.container():
            st.header("Login")
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")

            if st.button("Login", key="login_button", type="primary"):
                user = authenticate_user(username, password)
                if user:
                    st.session_state.update({
                        'authenticated': True,
                        'is_admin': user['is_admin'],
                        'username': user['username'],
                        'user_id': user['id'],
                        'current_page': "home"
                    })
                    st.rerun()
                else:
                    st.error("Invalid credentials")

    with col2:
        with st.container():
            st.header("New Here?")
            st.write("Create an account to get started")
            if st.button("Sign Up", key="show_signup_button"):
                st.session_state.show_signup = True
                st.rerun()


def show_signup():
    col1, col2 = st.columns(2)

    with col1:
        with st.container():
            st.header("Create Account")
            new_user = st.text_input("Username", key="signup_username")
            new_pass = st.text_input("Password", type="password", key="signup_password")

    with col2:
        with st.container():
            st.header(" ")  # Spacer
            confirm_pass = st.text_input("Confirm Password", type="password", key="confirm_password")
            if st.button("Create Account", key="signup_button"):
                if new_user and new_pass:
                    if new_pass == confirm_pass:
                        if add_user(new_user, new_pass):
                            st.success("Account created! Please login.")
                            st.session_state.show_signup = False
                            st.rerun()
                        else:
                            st.error("Username already exists")
                    else:
                        st.error("Passwords don't match")
                else:
                    st.error("Please fill all fields")

    if st.button("Back to Login", key="back_to_login"):
        st.session_state.show_signup = False
        st.rerun()


# Research components
def home_page():
    st.title(f"Welcome, {st.session_state.username}")
    st.markdown("---")
    st.header("Your AI-powered academic research assistant")

    cols = st.columns(4)
    features = [
        ("🔍 Discover Trends", "Find the latest trending research topics"),
        ("📚 Literature Reviews", "Generate comprehensive literature reviews"),
        ("❓ Research Questions", "Develop focused research questions"),
        ("📝 Academic Abstracts", "Create publication-ready abstracts")
    ]

    for i, (title, desc) in enumerate(features):
        with cols[i]:
            st.markdown(f"""
            <div style='
                background-color: white;
                border-radius: 8px;
                padding: 1.5rem;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                border-left: 4px solid #3498db;
                margin-bottom: 1rem;
                height: 100%;
            '>
                <h4 style='color: black;'>{title}</h4>
                <p style='color: black;'>{desc}</p>
            </div>
            """, unsafe_allow_html=True)


def research_dashboard():
    st.title("📚 Research Dashboard")
    st.markdown("---")

    # Fetch trending topics only if not already set
    if not st.session_state.trending_topics:
        with st.spinner("Loading trending topics..."):
            st.session_state.trending_topics = get_trending_topics()

    with st.container():
        st.header("🔍 Topic Selection")

        col1, col2 = st.columns([3, 2])
        with col1:
            st.subheader("🔥 Trending Topics")
            if st.session_state.trending_topics:
                st.session_state.selected_trending = st.radio(
                    "Choose from trending topics:",
                    st.session_state.trending_topics,
                    index=None,
                    key="trending_topics_radio"
                )
            else:
                st.warning("Unable to load trending topics. Please try refreshing.")

        with col2:
            st.subheader("✍️ Custom Topic")
            custom_topic = st.text_input(
                "Or enter your own topic:",
                key="custom_topic_input"
            )
            if st.button("🔄 Refresh Topics", key="refresh_topics"):
                with st.spinner("Refreshing trending topics..."):
                    st.session_state.trending_topics = get_trending_topics()
                    st.session_state.selected_trending = None
                st.rerun()

        if st.button("✅ Confirm Topic", key="confirm_topic"):
            if custom_topic.strip():
                st.session_state.final_topic = custom_topic.strip()
                st.session_state.topic_stage = "confirm"
                st.session_state.selected_trending = None
                st.rerun()
            elif st.session_state.selected_trending:
                st.session_state.final_topic = st.session_state.selected_trending
                st.session_state.topic_stage = "confirm"
                st.session_state.selected_trending = None
                st.rerun()
            else:
                st.warning("Please select a trending topic or enter a custom topic.")


def show_topic_confirmation():
    st.success(f"✅ Selected Topic: {st.session_state.final_topic}")

    subtopic_option = st.radio(
        "Next steps:",
        ["Generate Subtopics", "Proceed with Main Topic"],
        horizontal=True,
        key="subtopic_option"
    )

    if subtopic_option == "Generate Subtopics":
        handle_subtopic_generation()
    else:
        st.session_state.topic_stage = "generate"
        st.session_state.show_subtopic_section = False
        st.session_state.subtopics = []
        st.session_state.subtopic_round = 1
        st.rerun()


def handle_subtopic_generation():
    if not st.session_state.show_subtopic_section:
        st.session_state.show_subtopic_section = True
        st.session_state.subtopic_round = 1
        st.session_state.subtopics = []

    st.subheader(f"🔽 Subtopic Round {st.session_state.subtopic_round}")

    # Button to generate initial subtopics
    if st.session_state.subtopic_round == 1 and not st.session_state.subtopics:
        if st.button("Generate Subtopics Now", key="generate_subtopics_now"):
            with st.spinner("Generating subtopics..."):
                content = generate_research_content(st.session_state.final_topic, "analysis")
                subtopics = [line.split(". ", 1)[1].strip() for line in content.split("\n")
                             if line.strip() and line.strip()[0].isdigit() and ". " in line][:5]
                st.session_state.subtopics = subtopics if subtopics else ["Sample sub-topic " + str(i + 1) for i in
                                                                          range(5)]
            st.rerun()

    # Display subtopics if they exist
    if st.session_state.subtopics:
        current_subtopics = st.session_state.subtopics[
                            (st.session_state.subtopic_round - 1) * 5:st.session_state.subtopic_round * 5]
        if not current_subtopics:
            st.warning("No more subtopics available. Try generating more.")
        else:
            selected_subtopic = st.radio(
                "Select a subtopic:",
                current_subtopics,
                key=f"subtopic_radio_{st.session_state.subtopic_round}"
            )

            cols = st.columns(3)
            if cols[0].button("🔄 More Subtopics", key="more_subtopics"):
                with st.spinner("Generating more subtopics..."):
                    content = generate_research_content(st.session_state.final_topic, "analysis")
                    new_subtopics = [line.split(". ", 1)[1].strip() for line in content.split("\n")
                                     if line.strip() and line.strip()[0].isdigit() and ". " in line][:5]
                    new_subtopics = new_subtopics if new_subtopics else ["Sample sub-topic " + str(i + 1) for i in
                                                                         range(5)]
                    st.session_state.subtopics.extend(new_subtopics)
                    st.session_state.subtopic_round += 1
                st.rerun()

            if cols[1].button("✅ Confirm Subtopic", key="confirm_subtopic"):
                st.session_state.final_topic = selected_subtopic
                st.session_state.topic_stage = "generate"
                st.session_state.show_subtopic_section = False
                st.session_state.subtopics = []
                st.session_state.subtopic_round = 1
                st.rerun()
    else:
        st.info("Click 'Generate Subtopics Now' to generate subtopics.")


def show_research_output():
    st.divider()
    st.header(f"🧠 Research Output: {st.session_state.final_topic}")

    # Add custom CSS for white tab text
    st.markdown("""
    <style>
        /* Make all tab text white */
        .stTabs [role="tab"] {
            color: white !important;
        }

        /* Active tab styling */
        .stTabs [aria-selected="true"] {
            background-color: #3498db;
            font-weight: bold;
        }

        /* Inactive tab styling */
        .stTabs [role="tab"]:not([aria-selected="true"]) {
            background-color: #2c3e50;
            opacity: 0.8;
        }

        /* Hover effect */
        .stTabs [role="tab"]:hover {
            opacity: 1;
            border-color: white;
        }
    </style>
    """, unsafe_allow_html=True)

    tabs = st.tabs([
        "📝 Research Questions",
        "📚 Literature Review",
        "🔮 Future Directions",
        "📎 References",
        "🧠 Abstract",
        "📜 Full Analysis"
    ])

    with tabs[0]:
        show_research_questions()
    with tabs[1]:
        show_literature_review()
    with tabs[2]:
        show_future_directions()
    with tabs[3]:
        show_references()
    with tabs[4]:
        show_abstract()
    with tabs[5]:
        show_full_analysis()


def show_research_questions():
    st.subheader("Research Questions")
    content = generate_research_content(st.session_state.final_topic, "questions")
    st.markdown(content)
    add_download_button(content, "research_questions.md")


def show_literature_review():
    st.subheader("Literature Review")
    content = generate_research_content(st.session_state.final_topic, "literature")
    st.markdown(content)
    add_download_button(content, "literature_review.md")


def show_future_directions():
    st.subheader("Future Research Directions")
    content = generate_research_content(st.session_state.final_topic, "future")
    st.markdown(content)
    add_download_button(content, "future_directions.md")


def show_references():
    st.subheader("APA References")
    content = generate_research_content(st.session_state.final_topic, "references")
    st.markdown(content)
    add_download_button(content, "references.md")


def show_abstract():
    st.subheader("Academic Abstract")
    content = generate_research_content(st.session_state.final_topic, "abstract")
    st.markdown(content)
    add_download_button(content, "abstract.md")


def show_full_analysis():
    st.subheader("Comprehensive Analysis")
    content = generate_research_content(st.session_state.final_topic, "analysis")
    st.markdown(content)
    add_download_button(content, "full_analysis.md")


def add_download_button(content, filename):
    st.download_button(
        label="📥 Download",
        data=content,
        file_name=filename,
        mime="text/markdown"
    )


# Saved Projects
def saved_projects():
    st.title("📚 Saved Projects")
    st.markdown("---")

    if not st.session_state.authenticated:
        st.warning("Please login to view saved projects")
        return

    history = get_research_history(st.session_state.user_id)
    if not history:
        st.info("You don't have any saved research yet")
        return

    for item in history:
        with st.expander(f"{item[1]} - {item[2]} ({item[3].split()[0]})"):
            content = get_research_content(item[0])
            st.markdown(content)
            st.download_button(
                label="📥 Download",
                data=content,
                file_name=f"{item[1]}_{item[2]}.md",
                mime="text/markdown",
                key=f"download_{item[0]}"
            )


# Admin Panel
def admin_panel():
    st.title("👨‍💻 Admin Dashboard")
    st.markdown("---")

    tab1, tab2 = st.tabs(["User Management", "System Analytics"])

    with tab1:
        st.subheader("User Management")
        col1, col2 = st.columns(2)

        with col1:
            with st.expander("Add New User", expanded=True):
                new_user = st.text_input("Username", key="new_user")
                new_pass = st.text_input("Password", type="password", key="new_pass")
                new_role = st.selectbox("Role", ["user", "admin"], key="new_role")

                if st.button("Add User", key="add_user"):
                    if new_user and new_pass:
                        if add_user(new_user, new_pass, new_role):
                            st.success(f"User {new_user} added successfully!")
                        else:
                            st.error("Username already exists")
                    else:
                        st.error("Please enter both username and password")

        with col2:
            with st.expander("Current Users", expanded=True):
                conn = sqlite3.connect('scholarmind.db')
                c = conn.cursor()
                c.execute("SELECT id, username, role FROM users ORDER BY created_at DESC")
                users = c.fetchall()
                conn.close()

                if users:
                    df = pd.DataFrame(users, columns=["ID", "Username", "Role"])
                    st.dataframe(df, use_container_width=True)
                else:
                    st.warning("No users found")

    with tab2:
        st.subheader("System Analytics")
        st.write("Coming soon - system usage statistics and metrics")


# Main app flow
def main():
    if not st.session_state.authenticated:
        show_auth()
    else:
        show_authenticated_interface()


def show_authenticated_interface():
    st.sidebar.title(f"Welcome, {st.session_state.username}")
    if st.session_state.is_admin:
        st.sidebar.markdown("**Admin privileges** 🔑")

    if st.sidebar.button("Logout"):
        st.session_state.authenticated = False
        st.session_state.trending_topics = []
        st.session_state.subtopics = []
        st.session_state.subtopic_round = 1
        st.session_state.show_subtopic_section = False
        st.session_state.final_topic = None
        st.session_state.topic_stage = "selecting"
        st.session_state.selected_trending = None
        st.rerun()

    st.session_state.current_page = st.sidebar.radio(
        "Navigation",
        ["Home", "Research Assistant", "Saved Projects", "Settings"] +
        (["Admin Panel"] if st.session_state.is_admin else []),
        key="navigation"
    )

    route_page()


def route_page():
    if st.session_state.current_page == "Home":
        home_page()
    elif st.session_state.current_page == "Research Assistant":
        research_dashboard()

        if st.session_state.topic_stage == "confirm" and st.session_state.final_topic:
            show_topic_confirmation()
        elif st.session_state.topic_stage == "generate":
            show_research_output()
    elif st.session_state.current_page == "Saved Projects":
        saved_projects()
    elif st.session_state.current_page == "Settings":
        st.title("User Settings")
        st.info("This feature is coming soon!")
    elif st.session_state.current_page == "Admin Panel":
        admin_panel()


# Add this right before if __name__ == "__main__":
components.html("""
<script>
function setupHamburgerMenu() {
    const sidebar = document.querySelector('[data-testid="stSidebar"]');
    const hamburger = document.createElement('div');

    // Create hamburger button
    hamburger.innerHTML = `
        <style>
            .hamburger-btn {
                display: none;
                flex-direction: column;
                justify-content: space-around;
                width: 2rem;
                height: 2rem;
                background: transparent;
                border: none;
                cursor: pointer;
                padding: 0;
                z-index: 10;
                position: fixed;
                top: 1rem;
                left: 1rem;
            }
            .hamburger-btn div {
                width: 2rem;
                height: 0.25rem;
                background: #ecf0f1;
                border-radius: 10px;
                transition: all 0.3s linear;
            }
            @media (max-width: 768px) {
                .hamburger-btn {
                    display: flex;
                }
                [data-testid="stSidebar"] {
                    transform: translateX(-100%);
                    transition: transform 0.3s ease-in-out;
                    position: fixed !important;
                    height: 100vh !important;
                    z-index: 5;
                }
                [data-testid="stSidebar"].open {
                    transform: translateX(0);
                }
                [data-testid="collapsedControl"] {
                    display: none !important;
                }
            }
        </style>
        <button class="hamburger-btn" aria-label="Menu">
            <div></div>
            <div></div>
            <div></div>
        </button>
    `;
    document.body.appendChild(hamburger);

    // Toggle sidebar
    document.querySelector('.hamburger-btn').addEventListener('click', function() {
        sidebar.classList.toggle('open');
    });

    // Close when clicking outside on mobile
    document.addEventListener('click', function(event) {
        if (window.innerWidth <= 768 && 
            !sidebar.contains(event.target) && 
            !event.target.closest('.hamburger-btn') &&
            sidebar.classList.contains('open')) {
            sidebar.classList.remove('open');
        }
    });

    // Ensure sidebar is visible on desktop
    function handleResize() {
        if (window.innerWidth > 768) {
            sidebar.classList.add('open');
        }
    }

    window.addEventListener('resize', handleResize);
    handleResize();
}

if (document.readyState === 'complete') {
    setupHamburgerMenu();
} else {
    window.addEventListener('load', setupHamburgerMenu);
}
</script>
""", height=0)

if __name__ == "__main__":
    main()