# KinKeep Desktop: installation guide for beginners

No technical knowledge needed. Follow the steps in order. Total time: about 20 minutes the first time.
If anything looks different on your screen, stop and ask the person helping you. Nothing here can damage your computer.

**What KinKeep is:** a private program on your own computer that keeps your family's important information (accounts, insurance, documents, wills, emergency contacts) locked with your own password. Nothing is sent to the internet except the six-digit sign-in codes that KinKeep emails to *you*, from *your* own email account.

---

## Part 1. What you need

* A Windows 10 or 11 computer (or a Mac, see Part 12).
* An internet connection for the first setup only.
* An email address you can open (Gmail, Outlook, Yahoo or iCloud).
* A pen and paper or a printer. You will be given a **recovery key** that must be written down.
* The KinKeep folder, called **kinkeep-desktop**, given to you as a zip file (`kinkeep-desktop.zip`).

## Part 2. Put the KinKeep folder on your computer

1. Find **kinkeep-desktop.zip** (usually in your **Downloads** folder).
2. Right-click it and choose **Extract All...**, then click **Extract**.
3. A normal folder called **kinkeep-desktop** appears. Drag it into your **Documents** folder so you can find it later.

   > Important: do not run KinKeep from inside the zip file. Always extract it first.

## Part 3. Install Python (one time only)

Python is a free helper program that KinKeep needs in order to run.

1. Open your web browser and go to **python.org/downloads**.
2. Click the big yellow button **Download Python**. Wait for the file to download.
3. Open the downloaded file (in Downloads, called something like `python-3.12.x-amd64.exe`).
4. **Very important:** on the first screen, tick the box **"Add python.exe to PATH"** at the bottom.
5. Click **Install Now**. If Windows asks "Do you want to allow this app to make changes?", click **Yes**.
6. When it says **Setup was successful**, click **Close**.

## Part 4. Start KinKeep

1. Open your **Documents** folder, then the **kinkeep-desktop** folder.
2. Double-click **Start-KinKeep** (it may show as `Start-KinKeep.bat`).
3. If Windows says **"Windows protected your PC"**, click **More info**, then **Run anyway**. This message appears for any program that is not from a big company; the program is only the files in the folder you extracted.
4. A black window opens and says **First-time setup. Please wait**. It downloads what KinKeep needs. This takes 2 to 5 minutes. Do not close it. Lots of text scrolling is normal.
5. When it finishes, the **KinKeep window** opens by itself. You can leave the black window open; it closes with KinKeep.

Next time, just double-click **Start-KinKeep** again. It opens in a few seconds. Tip: right-click it, choose **Send to**, then **Desktop (create shortcut)** to put a shortcut on your desktop.

**If the black window says something went wrong:** take a photo or screenshot of it and send it to the person helping you. Common fix: close everything, then double-click **Start-KinKeep** again.

**If a window asks you to install "WebView2":** click the link it shows, install it, then start KinKeep again. (Most computers already have it.)

## Part 5. Create your account (first time only)

The KinKeep window shows **Create your account**.

1. **Your details:** first name, last name, email address, date of birth, and a **login name** you will remember (for example your first name).
2. **Master password:** this is the key to everything. Choose at least 10 characters. A sentence works well, for example `Blue kettle sings every morning`. Type it twice.
   * KinKeep **cannot** see or reset this password for you.
   * Write it down and keep it somewhere safe at home.
3. **Three security questions:** pick three questions and type your answers. They are a backup check when you forget your password. They never replace the emailed code.
4. **Email for sign-in codes:** choose your email provider and paste an **app password** (not your normal email password). How to get one:
   * **Gmail:** open myaccount.google.com, choose **Security**, turn on **2-Step Verification** if it is off, then search for **App passwords**, create one called KinKeep and copy the 16 letters.
   * **Outlook / Microsoft:** account.microsoft.com, **Security**, **Advanced security options**, **App passwords**.
   * **Yahoo / iCloud:** account security page, **Generate app password**.

   KinKeep sends the code from your own mailbox to yourself. There is no KinKeep server.
   If you skip this step, KinKeep still works in **demo mode**, but the code appears on screen, so it is **not** a real second lock. Set up email as soon as you can (Part 9).
5. Click **Continue**. KinKeep emails you a **6-digit code**. Open your email, type the code into KinKeep and click **Verify**.
6. **Choose how to start:** *An empty account* (a new vault), *The fictional sample family* (to practise), or *A backup I already have* if you have a KinKeep backup file. Then click **Create my account**.
7. **Your recovery key appears once.** It looks like `ABCD-EFGH-IJKL-...`.
   * **Write it down on paper or print the recovery sheet** and keep it away from the computer (for example with your important papers).
   * Click **Save a recovery sheet (.txt)** to keep a copy, print it, tick the box that says you saved the key, and click **Continue**.
   * Without this key, a forgotten password means starting from an empty vault.

You are now inside KinKeep.

## Part 6. Give family members their own sign-in and role

Only the **Owner** (you) and a **Co-owner** can do this. Use **Family & Care → Family and roles** in the left menu.

**The roles:**

| Role | In plain words |
|---|---|
| **Owner** | You. Can do everything. Only one Owner. |
| **Co-owner** | A trusted partner. Sees and changes everything and manages family members, but cannot change you or other Co-owners, and cannot use owner-only actions (clear data, emergency access, email settings). |
| **Adult Family Member** | Sees and changes nearly everything. Will and wish records are read-only and their private notes are hidden. |
| **Teen** | Sees the overview, reminders, emergency information, and only their own documents and identity records. Read-only. |
| **Viewer** | Read-only overview. |
| **Emergency Contact** | Sees only emergency essentials (emergency checklists, health insurance, contacts, the continuity plan), and only while you switch emergency access on. |

**To add a person:**

1. Open **Family and roles**.
2. Under **Add a family member**, type their **name** and pick their **role**.
3. To let them sign in now, click **Give them a sign-in now**, then type a **login name**, their **email address** (their codes go there) and a **starting password**. The **Suggest one** button creates a strong password for you.
4. Click **Add to family**.
5. **Tell them their login name and password in person.** Do not send the password by email or text.

**To change something later:** click the person's name in the **Family members** list. You can:

* change their **role** (it applies the next time they sign in),
* **set a new password** if they forgot theirs,
* **pause sign-in** (blocks them without deleting anything) and **turn it back on**,
* **remove their sign-in** or **remove them** from the list.

**Emergency access:** at the bottom of the page, choose how long (2 hours up to 7 days) and click **Allow emergency access**. Emergency Contacts can sign in only during that time. Click **Switch it off** when it is no longer needed.

**How a family member signs in:** they start KinKeep on a computer that has the same KinKeep data folder (see Part 7), type their own login name and password, then the 6-digit code that is emailed to them. They only see what their role allows.

## Part 7. Where your information is kept

KinKeep keeps everything in your **Documents** folder, in **KinKeep Data**:

| File | What it is |
|---|---|
| `kinkeep.vault.json` | Your locked vault. This is the main copy. |
| `kinkeep.data.xlsx` | A password-protected spreadsheet copy (see Part 10). |
| `backups` (folder) | Automatic older copies. |

Deleting the KinKeep program does **not** delete this folder.
To let a family member use KinKeep on **their own** computer, make a backup (Part 8), copy it to that computer and have them choose **A backup I already have** when creating the account there. Backups never carry family sign-ins, so you then give them a sign-in again (Part 6).

## Part 8. Make backups (do this regularly)

1. Open **Settings → Storage and security**.
2. Click **Save an encrypted vault backup (.json)** and also **Save a spreadsheet backup (.xlsx)**.
3. Save the files to a USB stick or a cloud folder (Google Drive, OneDrive). They stay locked with your master password, so this is safe.
4. Do this after big changes, and at least every month.

To restore, create or sign in to KinKeep, open **Storage and security**, choose the backup file, enter the password it was saved with, and confirm. Restoring never gives anyone access by itself: family members keep their roles but need you to approve them again.

## Part 9. Turn on real email codes later

Open **Storage and security → Email for sign-in codes**, choose your provider, paste the app password from Part 5 and save. The panel then says real email codes are on.

## Part 10. If KinKeep ever stops working

Your information is **not** trapped. Open **Documents → KinKeep Data → kinkeep.data.xlsx** with Microsoft Excel, LibreOffice or a similar program. When it asks for a password, type your **master password**. Each kind of information has its own sheet (Assets, Liabilities, Insurance and so on). Full instructions are in `docs/RECOVERY.md`.

Anyone with your master password and that file can read it, so keep both private.

## Part 11. Problems and answers

| Problem | What to do |
|---|---|
| Nothing happens when I double-click Start-KinKeep | Make sure the folder was extracted (Part 2) and is not still inside the zip file. |
| "Python is not installed" | Do Part 3 again and make sure **Add python.exe to PATH** is ticked. |
| The black window shows red text | Take a screenshot and send it to your helper. Then try again with a working internet connection. |
| I did not get the email code | Wait 30 seconds, check the spam folder, then click **Resend code**. You can ask for at most 6 per hour. |
| "Too many wrong tries" | Wait for the time shown (it starts at 15 seconds) and try again. Check the password and Caps Lock. |
| I forgot my master password | On the sign-in screen click **Forgot your password?**. You need your three answers, an emailed code and, to keep your data, your recovery key. |
| A family member says their sign-in is paused | The Owner opens **Family and roles**, clicks the person and chooses **Turn sign-in back on**. |
| I lost my recovery key | Sign in, open **Storage and security**, and make a new one. The old key stops working. |

## Part 12. Installing on a Mac

1. Extract the zip by double-clicking it, then drag **kinkeep-desktop** into **Documents**.
2. Install Python from **python.org/downloads/macos** (open the downloaded `.pkg` and keep clicking Continue).
3. Open the **kinkeep-desktop** folder. **Right-click** `start-kinkeep.command`, choose **Open**, then **Open** again in the warning box (needed only the first time).
4. If macOS says the file cannot be opened because of permissions, open the **Terminal** app, type `chmod +x ` (with a space), drag the file onto the Terminal window, press Return, then try step 3 again.
5. Wait for the first-time setup, then continue from **Part 5** above. On a Mac the data folder is also **Documents → KinKeep Data**.

---

*Note for the person helping: this guide covers running KinKeep from the source folder, which is the tested route. A ready-made installer (`KinKeep.exe` or `KinKeep.app`) is built by the GitHub workflow in `.github/workflows/desktop.yml`; when you have one, Part 3 and Part 4 are replaced by "unzip and double-click KinKeep". Unsigned builds show a one-time "Windows protected your PC" (More info, Run anyway) or macOS right-click Open warning.*
