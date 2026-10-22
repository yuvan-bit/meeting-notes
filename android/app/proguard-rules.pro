# Keep kotlinx.serialization generated serializers
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class com.meetingnotes.app.data.** {
    *** Companion;
}
-keepclasseswithmembers class com.meetingnotes.app.data.** {
    kotlinx.serialization.KSerializer serializer(...);
}
