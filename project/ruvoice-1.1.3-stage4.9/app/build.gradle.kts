import java.util.Properties
import java.util.zip.ZipFile

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Ключ релизной подписи — в local.properties (не в git): release.storeFile/storePassword/keyAlias/keyPassword.
val localProps = Properties().apply { rootProject.file("local.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) } }

android {
    namespace = "ru.kost.ruvoice"
    compileSdk = 35
    defaultConfig {
        // Isolated Stage 4.17 package: can be installed beside official RuVoice and Stage 4.16
        // without uninstalling the previous test build or deleting its downloaded RUAccent model.
        applicationId = "ru.kost.ruvoice.improved.stage417"
        // ONNX Runtime Android 1.32.0 requires API 24; official RuVoice stays untouched.
        minSdk = 24
        targetSdk = 35
        versionCode = 10111
        versionName = "1.1.3-improved-4.17"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a") }
    }
    // full — модель v5_5_ru в APK (app/src/full/assets/silero), lite — без неё: штатные голоса ставятся
    // паком ruvoice-pack-ru.zip, обновление приложения не тянет 85 МБ модели. applicationId и versionCode
    // одни — ставятся друг поверх друга, паки и настройки сохраняются.
    flavorDimensions += "model"
    productFlavors {
        create("full") { dimension = "model"; buildConfigField("boolean", "BUILTIN_MODEL", "true") }
        create("lite") { dimension = "model"; buildConfigField("boolean", "BUILTIN_MODEL", "false"); versionNameSuffix = "-lite" }
    }
    buildFeatures { buildConfig = true }
    signingConfigs {
        localProps.getProperty("release.storeFile")?.let { path ->
            create("release") {
                storeFile = file(path)
                storePassword = localProps.getProperty("release.storePassword")
                keyAlias = localProps.getProperty("release.keyAlias")
                keyPassword = localProps.getProperty("release.keyPassword")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
        // debug тем же ключом: ставится поверх релиза с телефона без удаления настроек и словарей
        debug { signingConfigs.findByName("release")?.let { signingConfig = it } }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    androidResources {
        noCompress += listOf("ptl", "pte", "json", "bin")
        // silero_ru.json и eyo_safe.txt в APK не нужны: приложение читает собранный из них stress.bin (задача stressBin)
        ignoreAssetsPattern = "!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:!thumbs.db:!picasa.ini:!*~:!silero_ru.json:!eyo_safe.txt"
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
        // перезапись эталона RuPathSnapshotTest: ./gradlew … -Druvoice.snapshot.write=true
        unitTests.all { t ->
            // Whole-book paired evaluation retains per-token diagnostics until the JSON report is written.
            // Give the test worker its own heap; org.gradle.jvmargs configures only the Gradle daemon.
            t.maxHeapSize = "3g"
            System.getProperty("ruvoice.snapshot.write")?.let { t.systemProperty("ruvoice.snapshot.write", it) }
        }
    }
    // libfbjni/libc++_shared есть и в pytorch_android_lite, и в executorch; из lite годятся обоим
    packaging { jniLibs.useLegacyPackaging = false; jniLibs.pickFirsts += listOf("lib/*/libfbjni.so", "lib/*/libc++_shared.so") }
}

// Словари ударений и «ё» одним бинарным файлом: mmap вместо разбора json при запуске процесса (StressBin)
val stressBin = tasks.register<StressBinTask>("stressBin") {
    json.set(file("src/main/assets/silero/silero_ru.json"))
    eyo.set(file("src/main/assets/eyo_safe.txt"))
    outDir.set(layout.buildDirectory.dir("generated/stressBin"))
}
androidComponents { onVariants { it.sources.assets?.addGeneratedSourceDirectory(stressBin, StressBinTask::outDir) } }

/**
 * Desktop runtime for the full-book audit. It uses the same production app classes and
 * the JUnit test entry point as CI, plus the resolved JVM dependencies. The Windows
 * package adds its own JRE, model workers, official Silero assets and native tokenizer.
 */
val desktopAuditRuntimeClasspath = configurations.named("fullDebugUnitTestRuntimeClasspath")
val desktopAuditCompileClasspath = configurations.named("fullDebugUnitTestCompileClasspath")

tasks.register<Sync>("assembleDesktopAuditRuntime") {
    dependsOn(
        "compileFullDebugKotlin",
        "compileFullDebugJavaWithJavac",
        "compileFullDebugUnitTestKotlin",
        "compileFullDebugUnitTestJavaWithJavac",
    )
    into(layout.buildDirectory.dir("desktop-audit"))
    from(layout.buildDirectory.dir("tmp/kotlin-classes/fullDebug")) { into("classes") }
    from(layout.buildDirectory.dir("intermediates/javac/fullDebug/compileFullDebugJavaWithJavac/classes")) { into("classes") }
    from(layout.buildDirectory.dir("tmp/kotlin-classes/fullDebugUnitTest")) { into("classes") }
    from(layout.buildDirectory.dir("intermediates/javac/fullDebugUnitTest/compileFullDebugUnitTestJavaWithJavac/classes")) { into("classes") }
    from(desktopAuditRuntimeClasspath) { into("lib") }
    from(desktopAuditCompileClasspath) { into("lib") }
    // AGP's mockable android.jar is needed when production classes touch Android APIs on the desktop JVM.
    from(fileTree(layout.buildDirectory).matching { include("**/mockable-android*.jar") }) { into("lib") }
    duplicatesStrategy = org.gradle.api.file.DuplicatesStrategy.EXCLUDE
    doLast {
        val root = layout.buildDirectory.dir("desktop-audit/classes").get().asFile
        check(root.resolve("ru/kost/ruvoice/text/UploadedEpubPairedEvaluationMain.class").isFile) {
            "Desktop whole-book main entry point was not compiled"
        }
        check(root.resolve("ru/kost/ruvoice/text/UploadedEpubPairedEvaluationTest.class").isFile) {
            "Desktop whole-book JUnit test class was not compiled"
        }
        val lib = layout.buildDirectory.dir("desktop-audit/lib").get().asFile
        val jars = lib.listFiles()?.filter { it.extension == "jar" }.orEmpty()
        check(jars.isNotEmpty()) { "Desktop whole-book audit dependencies were not packaged" }
        fun contains(entry: String) = jars.any { jar ->
            runCatching { ZipFile(jar).use { archive -> archive.getEntry(entry) != null } }.getOrDefault(false)
        }
        check(contains("org/junit/runner/JUnitCore.class")) { "JUnit runtime was not packaged" }
        check(contains("org/json/JSONObject.class")) { "JSON runtime was not packaged" }
        check(contains("android/util/Log.class")) { "Mockable Android API classes were not packaged" }
    }
}

dependencies {
    implementation("org.pytorch:pytorch_android_lite:2.1.0")
    // ExecuTorch 1.5.0 + XNNPACK для бэкбона вокодера (backbone.pte): в Maven Central только 0.6.0. AAR собран
    // tools/build_executorch_aar.sh — готовый с ossci-android.s3.amazonaws.com падает SIGILL на ARMv8.0 (см. скрипт).
    implementation(files("libs/executorch-1.5.0-xnnpack.aar"))
    implementation("com.facebook.soloader:soloader:0.10.5")
    // Локальная нейросетевая проверка ударений и «ё» (CPU, полностью офлайн после загрузки весов).
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.32.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.viewpager2:viewpager2:1.1.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    // Espresso с проверками доступности (AccessibilityChecksTest)
    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation("androidx.test.espresso:espresso-accessibility:3.6.1")
}
