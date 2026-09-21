<!DOCTYPE html>
<html lang="vi">

<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Đăng nhập - SSO</title>
    <link rel="icon" type="image/x-icon" href="<?= base_url('access/images/logo_truong_only.png') ?>">
    <link rel="preload" href="/access/fonts/Momo_Trust_Sans/MomoTrustSans-Regular.ttf" as="font" type="font/ttf" crossorigin>
    <link rel="preload" href="/access/fonts/Momo_Trust_Sans/MomoTrustSans-Medium.ttf" as="font" type="font/ttf" crossorigin>
    <style>
        @font-face {
            font-family: 'Momo Trust Sans Login';
            src: url('/access/fonts/Momo_Trust_Sans/MomoTrustSans-Regular.ttf') format('truetype');
            font-weight: 400;
            font-style: normal;
            font-display: swap;
        }

        @font-face {
            font-family: 'Momo Trust Sans Login';
            src: url('/access/fonts/Momo_Trust_Sans/MomoTrustSans-Medium.ttf') format('truetype');
            font-weight: 500;
            font-style: normal;
            font-display: swap;
        }

        @font-face {
            font-family: 'Momo Trust Sans Login';
            src: url('/access/fonts/Momo_Trust_Sans/MomoTrustSans-SemiBold.ttf') format('truetype');
            font-weight: 600;
            font-style: normal;
            font-display: swap;
        }

        @font-face {
            font-family: 'Momo Trust Sans Login';
            src: url('/access/fonts/Momo_Trust_Sans/MomoTrustSans-Bold.ttf') format('truetype');
            font-weight: 700;
            font-style: normal;
            font-display: swap;
        }

        :root {
            color-scheme: light;
            --font-family: 'Momo Trust Sans Login', Arial, sans-serif;
            --md-primary: #4f6f9f;
            --md-on-primary: #ffffff;
            --md-primary-container: #e3edf9;
            --md-on-primary-container: #263c5b;
            --md-secondary-container: #e9eff7;
            --md-on-secondary-container: #344355;
            --md-surface: #f8faff;
            --md-surface-container: #f0f4fa;
            --md-surface-container-high: #e8edf5;
            --md-on-surface: #26313f;
            --md-on-surface-variant: #5f6b7a;
            --md-outline: #8c99aa;
            --md-outline-variant: #e2e8f0;
            --md-error-container: #fbe4e1;
            --md-on-error-container: #68201d;
        }

        *,
        *::before,
        *::after {
            box-sizing: border-box;
        }

        html {
            min-width: 320px;
            background: var(--md-surface);
            font-family: var(--font-family);
            font-synthesis: none;
        }

        body,
        button,
        input,
        select,
        textarea {
            font-family: var(--font-family);
        }

        body {
            min-height: 100vh;
            min-height: 100dvh;
            margin: 0;
            padding: 32px 20px;
            overflow-x: hidden;
            display: grid;
            place-items: center;
            position: relative;
            font-family: inherit;
            font-size: 15px;
            line-height: 1.5;
            color: var(--md-on-surface);
            background:
                radial-gradient(circle, rgba(79, 111, 159, .14) 1px, transparent 1.2px) 0 0 / 24px 24px,
                radial-gradient(circle at 12% 16%, rgba(211, 228, 248, .58) 0 7%, transparent 7.2%),
                radial-gradient(circle at 88% 84%, rgba(226, 236, 248, .72) 0 10%, transparent 10.2%),
                linear-gradient(145deg, #f8faff 0%, #fff 48%, #f2f6fb 100%);
        }

        .background-shape {
            position: fixed;
            z-index: 0;
            pointer-events: none;
            filter: blur(.2px);
            opacity: .58;
        }

        .background-shape--one {
            width: 280px;
            height: 190px;
            top: -70px;
            right: -85px;
            border-radius: 42% 58% 62% 38% / 48% 36% 64% 52%;
            background: var(--md-primary-container);
            transform: rotate(12deg);
        }

        .background-shape--two {
            width: 230px;
            height: 230px;
            bottom: -115px;
            left: -70px;
            border-radius: 63% 37% 43% 57% / 42% 61% 39% 58%;
            background: var(--md-secondary-container);
            transform: rotate(-18deg);
        }

        .container {
            width: min(100%, 500px);
            position: relative;
            z-index: 1;
            padding: 38px 36px 28px;
            border: 0;
            border-radius: 36px;
            background: #fff;
            box-shadow: 0 1px 2px rgba(38, 60, 91, .025), 0 12px 36px rgba(38, 60, 91, .055);
            backdrop-filter: blur(18px);
        }

        .brand-mark {
            width: 92px;
            height: 92px;
            display: grid;
            place-items: center;
            margin: 0 auto 20px;
            border-radius: 30px 30px 30px 12px;
            background: #F8FAFC;
            transform: rotate(-2deg);
        }

        .logo {
            display: block;
            width: auto;
            height: 68px;
            transform: rotate(2deg);
        }

        .eyebrow {
            margin: 0 0 8px;
            color: #b3261e;
            font-size: 12px;
            line-height: 1.3;
            font-weight: 600;
            letter-spacing: .1em;
            text-align: center;
            text-transform: uppercase;
        }

        .page-title {
            display: block;
            width: 100% !important;
            max-width: none;
            margin: 15px 0 15px;
            color: var(--md-on-surface);
            font-size: clamp(22px, 5vw, 25px);
            line-height: 1.18;
            font-weight: 500;
            letter-spacing: -.025em;
            text-align: center !important;
        }

        .subtitle {
            max-width: 360px;
            margin: 0 auto 30px;
            color: var(--md-on-surface-variant);
            font-size: 15px;
            line-height: 1.55;
            text-align: center;
        }

        .account-list {
            max-height: 340px;
            margin: 0 -4px 24px;
            padding: 4px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .account-card {
            padding: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            border: 1px solid transparent;
            border-radius: 22px;
            background: rgb(246 246 255 / 94%);
            transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease;
        }

        .account-card:hover {
            border-color: var(--md-outline-variant);
            box-shadow: 0 3px 10px rgba(38, 60, 91, .045);
            transform: translateY(-1px);
        }

        .account-info {
            flex: 1;
            min-width: 0;
            font-size: 14px;
            color: var(--md-on-surface-variant);
        }

        .account-info span {
            display: block;
            word-break: break-word;
            overflow-wrap: break-word;
        }

        .account-info strong {
            color: var(--md-on-surface);
            font-size: 15px;
            font-weight: 600;
        }

        .account-provider {
            margin-top: 3px;
            color: var(--md-outline);
            font-size: 12px;
        }

        .account-actions {
            display: flex;
            flex-shrink: 0;
            gap: 8px;
        }

        form {
            display: block;
            max-width: 100%;
        }

        button {
            min-height: 42px;
            padding: 9px 16px;
            border: 0;
            border-radius: 999px;
            font: inherit;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: background-color .2s ease, box-shadow .2s ease, transform .15s ease;
        }

        button:active,
        .social-button:active {
            transform: scale(.98);
        }

        .btn-primary {
            color: var(--md-on-primary);
            background: var(--md-primary);
            box-shadow: 0 2px 5px rgba(79, 111, 159, .14);
        }

        .btn-primary:hover {
            background: #42618f;
            box-shadow: 0 3px 8px rgba(79, 111, 159, .16);
        }

        .btn-secondary {
            color: var(--md-on-secondary-container);
            background: var(--md-secondary-container);
        }

        .btn-secondary:hover {
            background: #dfe7f1;
        }

        .link {
            width: fit-content;
            display: block;
            margin: 8px auto 0;
            padding: 10px 18px;
            border-radius: 999px;
            color: var(--md-primary);
            font-size: 14px;
            font-weight: 500;
            text-align: center;
            text-decoration: none;
            transition: background-color .2s ease;
        }

        .link:hover {
            background: var(--md-primary-container);
        }

        .social-login {
            margin-top: 24px;
        }

        .social-buttons {
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .social-button {
            min-height: 58px;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            padding: 14px 54px;
            border: 1px solid transparent;
            border-radius: 19px;
            background: rgb(246 246 255 / 94%);
            color: var(--md-on-surface);
            font-size: 15px;
            font-weight: 500;
            text-align: center;
            text-decoration: none;
            transition: background-color .2s ease, border-color .2s ease, box-shadow .2s ease, transform .15s ease;
        }

        .social-button:hover {
            border-color: var(--md-outline-variant);
            background: var(--md-surface-container);
            box-shadow: 0 2px 7px rgba(38, 60, 91, .04);
        }

        .social-button > .social-icon,
        .social-button > img {
            width: 22px;
            height: 22px;
            position: absolute;
            top: 50%;
            left: 20px;
            transform: translateY(-50%);
            object-fit: contain;
        }

        .divider {
            display: flex;
            align-items: center;
            margin: 26px 0 20px;
            color: var(--md-outline);
            font-size: 13px;
            font-weight: 500;
            text-align: center;
        }

        .divider::before,
        .divider::after {
            content: '';
            flex: 1;
            border-bottom: 1px solid var(--md-outline-variant);
        }

        .divider::before { margin-right: 14px; }
        .divider::after { margin-left: 14px; }

        .error,
        .message {
            margin-bottom: 22px;
            padding: 14px 16px;
            border-radius: 18px;
            font-size: 14px;
        }

        .error {
            border: 0;
            background: var(--md-error-container);
            color: var(--md-on-error-container);
        }

        .message {
            border: 0;
            background: #f0f2fa;
            color: #424a67;
        }

        .security-note {
            margin: 26px 0 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 7px;
            color: var(--md-outline);
            font-size: 12px;
            text-align: center;
        }

        .security-note svg {
            width: 17px;
            height: 17px;
            flex: 0 0 auto;
        }

        :focus-visible {
            outline: 3px solid rgba(79, 111, 159, .22);
            outline-offset: 3px;
        }

        @media (max-width: 560px) {
            body {
                padding: 16px 12px;
                align-items: start;
            }

            .container {
                margin: auto 0;
                padding: 30px 20px 24px;
                border-radius: 30px;
            }

            .brand-mark {
                width: 82px;
                height: 82px;
                border-radius: 26px 26px 26px 10px;
            }

            .logo { height: 60px; }

            .account-card {
                align-items: flex-start;
                flex-direction: column;
            }

            .account-actions,
            .account-actions form {
                width: 100%;
            }

            .account-actions button {
                width: 100%;
            }
        }

        @media (prefers-reduced-motion: reduce) {
            *,
            *::before,
            *::after {
                scroll-behavior: auto !important;
                transition-duration: .01ms !important;
            }
        }
    </style>
</head>

<body>
    <div class="background-shape background-shape--one" aria-hidden="true"></div>
    <div class="background-shape background-shape--two" aria-hidden="true"></div>
    <div class="container">
        <div class="brand-mark">
            <img class="logo" src="<?= base_url('access/images/logo_truong_only.png') ?>" alt="ĐNC — Nam Can Tho University">
        </div>
        <!-- <p class="eyebrow">Trường Đại học Nam Cần Thơ</p> -->
        <h3 class="page-title"><?= $showAddForm ? 'Đăng nhập vào SSO' : 'Chọn tài khoản' ?></h3>
        <p class="subtitle"><?= $showAddForm ? 'Kết nối an toàn với tài khoản của bạn' : 'Chọn tài khoản đã lưu để tiếp tục' ?></p>

        <?php if (!empty($message)): ?>
            <div class="message">
                <?= esc($message) ?>
            </div>
        <?php endif; ?>

        <?php if (!empty($errors)): ?>
            <div class="error">
                <ul style="margin: 0; padding-left: 18px;">
                    <?php foreach ($errors as $error): ?>
                        <li><?= esc($error) ?></li>
                    <?php endforeach; ?>
                </ul>
            </div>
        <?php endif; ?>

        <?php if (!$showAddForm && !empty($accounts)): ?>
            <div class="account-list">
                <?php foreach ($accounts as $account): ?>
                    <div class="account-card">
                        <div class="account-info">
                            <span><strong><?= esc($account['name'] ?? $account['email']) ?></strong></span>
                            <span class="truncate"><?= esc($account['email']) ?></span>
                            <?php if (!empty($account['provider'])): ?>
                                <span class="account-provider">Đã đăng nhập bằng
                                    <?= esc(ucfirst($account['provider'])) ?></span>
                            <?php endif; ?>
                        </div>
                        <div class="account-actions">
                            <form method="post" action="<?= site_url('auth/switch/' . urlencode($account['id'])) ?>">
                                <?= csrf_field() ?>
                                <button type="submit" class="btn-primary">Sử dụng</button>
                            </form>
                            <form method="post" action="<?= site_url('auth/remove/' . urlencode($account['id'])) ?>">
                                <?= csrf_field() ?>
                                <button type="submit" class="btn-secondary">Xoá</button>
                            </form>
                        </div>
                    </div>
                <?php endforeach; ?>
            </div>
            <a class="link" href="<?= site_url('auth/login?mode=add') ?>">Sử dụng tài khoản khác</a>
            <?php if (!empty($socialProviders)): ?>
                <div class="divider">Hoặc tiếp tục với</div>
                <div class="social-buttons">
                    <?php foreach ($socialProviders as $provider => $label): ?>
                        <a class="social-button" href="<?= site_url('auth/social/' . urlencode($provider)) ?>">
                            <?php if ($provider === 'google'): ?>
                                <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path
                                        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                                        fill="#4285F4" />
                                    <path
                                        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                                        fill="#34A853" />
                                    <path
                                        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                                        fill="#FBBC05" />
                                    <path
                                        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                                        fill="#EA4335" />
                                </svg>
                            <?php elseif ($provider === 'facebook'): ?>
                                <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path
                                        d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"
                                        fill="#1877F2" />
                                </svg>
                            <?php elseif ($provider === 'github'): ?>
                                <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path
                                        d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"
                                        fill="#181717" />
                                </svg>
                            <?php elseif ($provider === 'linkedin'): ?>
                                <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path
                                        d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"
                                        fill="#0A66C2" />
                                </svg>
                            <?php elseif ($provider === 'zalo'): ?>
                                <img src="<?= base_url('access/images/logo-zalo.png') ?>" alt="Logo Zalo" width="20">
                            <?php elseif ($provider === 'apple'): ?>
                                <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path
                                        d="M17.05 20.28c-.98.95-2.05.88-3.08.4-1.09-.5-2.08-.48-3.24 0-1.44.62-2.2.44-3.06-.4C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09l.01-.01zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"
                                        fill="#000000" />
                                </svg>
                            <?php endif; ?>
                            <div>Đăng nhập với <?= esc($label) ?></div>
                        </a>
                    <?php endforeach; ?>
                </div>
            <?php endif; ?>
        <?php else: ?>

            <?php if (!empty($accounts)): ?>
                <div class="mt-2">
                    <a class="link" href="<?= site_url('auth/login') ?>">Chọn từ tài khoản đã lưu</a>
                </div>
            <?php endif; ?>

            <?php if (!empty($socialProviders)): ?>
                <div class="social-login">
                    <div class="social-buttons">
                        <?php foreach ($socialProviders as $provider => $label): ?>
                            <a class="social-button" href="<?= site_url('auth/social/' . urlencode($provider)) ?>">
                                <?php if ($provider === 'google'): ?>
                                    <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path
                                            d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                                            fill="#4285F4" />
                                        <path
                                            d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                                            fill="#34A853" />
                                        <path
                                            d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                                            fill="#FBBC05" />
                                        <path
                                            d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                                            fill="#EA4335" />
                                    </svg>
                                <?php elseif ($provider === 'facebook'): ?>
                                    <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path
                                            d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"
                                            fill="#1877F2" />
                                    </svg>
                                <?php elseif ($provider === 'github'): ?>
                                    <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path
                                            d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"
                                            fill="#181717" />
                                    </svg>
                                <?php elseif ($provider === 'linkedin'): ?>
                                    <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path
                                            d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"
                                            fill="#0A66C2" />
                                    </svg>
                                <?php elseif ($provider === 'zalo'): ?>
                                    <img src="<?= base_url('access/images/logo-zalo.png') ?>" alt="Logo Zalo" width="20">
                                <?php elseif ($provider === 'apple'): ?>
                                    <svg class="social-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path
                                            d="M17.05 20.28c-.98.95-2.05.88-3.08.4-1.09-.5-2.08-.48-3.24 0-1.44.62-2.2.44-3.06-.4C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09l.01-.01zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"
                                            fill="#000000" />
                                    </svg>
                                <?php endif; ?>
                                Đăng nhập với <?= esc($label) ?>
                            </a>
                        <?php endforeach; ?>
                    </div>
                </div>
            <?php endif; ?>
        <?php endif; ?>
        <p class="security-note">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 3 5 6v5c0 4.6 3 8.6 7 10 4-1.4 7-5.4 7-10V6l-7-3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                <path d="m9.2 12 1.8 1.8 3.8-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            Phiên đăng nhập được bảo vệ bởi SSO
        </p>
    </div>
</body>

</html>
