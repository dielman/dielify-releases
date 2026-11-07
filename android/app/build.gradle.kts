plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Same version as the PC app (src/dielify/__init__.py) so it's obvious which belong together.
val dielifyVersion: String = Regex("""__version__ = "([^"]+)"""")
    .find(rootProject.file("../src/dielify/__init__.py").readText())!!.groupValues[1]

// Where updates are published (same manifest as the PC app; written by tools/release.py).
val manifestUrl: String = Regex("""MANIFEST_URL: str \| None = '([^']*)'""")
    .find(rootProject.file("../src/dielify/update_config.py").readText())?.groupValues?.get(1) ?: ""

// Release signing: tools/release.py passes the keystore (kept outside the project).
val releaseKeystore: String? = System.getenv("DIELIFY_KEYSTORE")

android {
    namespace = "com.dielify.app"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.dielify.app"
        minSdk = 29
        targetSdk = 37
        versionName = dielifyVersion
        versionCode = dielifyVersion.split(".").fold(0) { acc, part -> acc * 100 + part.toInt() }
        buildConfigField("String", "MANIFEST_URL", "\"$manifestUrl\"")
    }

    signingConfigs {
        if (releaseKeystore != null) create("release") {
            storeFile = file(releaseKeystore)
            storePassword = System.getenv("DIELIFY_KEYSTORE_PASSWORD")
            keyAlias = "dielify"
            keyPassword = System.getenv("DIELIFY_KEYSTORE_PASSWORD")
        }
    }

    buildTypes {
        debug {
            // Test builds sit next to the real app instead of replacing it.
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-test"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (releaseKeystore != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    implementation(libs.compose.tooling.preview)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.session)
    implementation(libs.media3.okhttp)
    implementation(libs.okhttp)
    implementation(libs.serialization.json)
    implementation(libs.coil.compose)
    implementation(libs.coil.okhttp)
    implementation(libs.work)
}
