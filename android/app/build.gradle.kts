plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Same version as the PC app (src/dielify/__init__.py) so it's obvious which belong together.
val dielifyVersion: String = Regex("""__version__ = "([^"]+)"""")
    .find(rootProject.file("../src/dielify/__init__.py").readText())!!.groupValues[1]

android {
    namespace = "com.dielify.app"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.dielify.app"
        minSdk = 29
        targetSdk = 37
        versionName = dielifyVersion
        versionCode = dielifyVersion.split(".").fold(0) { acc, part -> acc * 100 + part.toInt() }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
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
