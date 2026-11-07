# Libraries (Media3, WorkManager, kotlinx.serialization, OkHttp, Coil) ship their own rules.
# Our @Serializable models: keep their generated serializers.
-keepclassmembers @kotlinx.serialization.Serializable class com.dielify.app.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.dielify.app.**$$serializer { *; }
