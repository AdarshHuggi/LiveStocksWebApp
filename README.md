# PashuNivesh setup

## Start the app

1. Copy `.env.example` to `.env` and replace the example values.
2. Set a long random `SECRET_KEY`, plus `ADMIN_EMAIL` and a unique 12-72 byte `ADMIN_PASSWORD`.
3. Install the project dependencies with `pip install -r requirements.txt`.
4. Start the server from this project folder with `uvicorn main:app --reload`.
5. Sign in at `/admin/login`. The configured administrator can create farms, publish and edit animal listings, upload photos, disable listings, and review payment activity.

The admin account is created or promoted during application startup from `ADMIN_EMAIL` and `ADMIN_PASSWORD`. Admin access is not available through public registration.

## Configure Razorpay payments

Add Razorpay API keys to `.env`. Start with Test Mode keys (`RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`) and make a test payment before switching to Live Mode. The server creates each order using the listed animal price in INR paise, verifies the checkout signature, confirms the payment status with Razorpay, and only then records the investment.

For a deployed app, configure the Razorpay webhook URL as `https://your-domain/payments/razorpay/webhook`, subscribe to `payment.captured` and `payment.failed`, and set the same webhook secret as `RAZORPAY_WEBHOOK_SECRET`. Keep all secrets in the server environment; never put the API secret in HTML or JavaScript.

Razorpay Checkout requires an account and valid keys. Until configured, the marketplace keeps purchase buttons disabled. Orders that remain pending for 30 minutes release their animal listing. A captured payment for an animal that has since become unavailable is marked for administrator refund review.

Existing SQLite animal tables are upgraded at startup. The app creates the `payments` table automatically.
