package com.dielify.app.playback

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.widget.RemoteViews
import androidx.media3.common.Player
import com.dielify.app.R
import com.dielify.app.ui.MainActivity

/**
 * The home-screen widget: cover, song, artist (or "Playing on <device>" / "On a speaker")
 * and previous / play-pause / next. It shows whatever the app's player shows, so it follows
 * the active device and casting too.
 *
 * The buttons talk to the running PlaybackService (they arrive here as broadcasts and go to
 * its player). When nothing is playing, the service isn't running: then the whole widget
 * just opens the app.
 */
class PlayerWidget : AppWidgetProvider() {

    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        show(context, last)
    }

    override fun onReceive(context: Context, intent: Intent) {
        val player = PlaybackService.current?.shownPlayer()
        when (intent.action) {
            ACTION_PLAY -> player?.let { if (it.isPlaying) it.pause() else { if (it.playbackState == Player.STATE_IDLE) it.prepare(); it.play() } }
                ?: openApp(context)
            ACTION_NEXT -> player?.seekToNext()
            ACTION_PREV -> player?.seekToPrevious()
            else -> super.onReceive(context, intent)
        }
    }

    private fun openApp(context: Context) {
        context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    /** What the widget shows. */
    data class State(
        val title: String? = null,
        val subtitle: String? = null,
        val playing: Boolean = false,
        val cover: Bitmap? = null,
        val active: Boolean = false,   // the player service is running (buttons work)
    )

    companion object {
        private const val ACTION_PLAY = "com.dielify.app.widget.PLAY"
        private const val ACTION_NEXT = "com.dielify.app.widget.NEXT"
        private const val ACTION_PREV = "com.dielify.app.widget.PREV"

        @Volatile private var last = State()

        private fun broadcast(context: Context, action: String, code: Int): PendingIntent =
            PendingIntent.getBroadcast(context, code, Intent(context, PlayerWidget::class.java).setAction(action),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

        fun show(context: Context, state: State) {
            last = state
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, PlayerWidget::class.java))
            if (ids.isEmpty()) return
            val open = PendingIntent.getActivity(context, 0,
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val v = RemoteViews(context.packageName, R.layout.widget_player)
            v.setTextViewText(R.id.widget_title, state.title ?: context.getString(R.string.widget_nothing))
            v.setTextViewText(R.id.widget_subtitle, state.subtitle ?: context.getString(R.string.widget_open))
            if (state.cover != null) v.setImageViewBitmap(R.id.widget_cover, state.cover)
            else v.setImageViewResource(R.id.widget_cover, R.drawable.ic_widget_note)
            v.setImageViewResource(R.id.widget_play, if (state.playing) R.drawable.ic_widget_pause else R.drawable.ic_widget_play)
            v.setOnClickPendingIntent(R.id.widget_root, open)
            v.setOnClickPendingIntent(R.id.widget_cover, open)
            if (state.active) {
                v.setOnClickPendingIntent(R.id.widget_play, broadcast(context, ACTION_PLAY, 1))
                v.setOnClickPendingIntent(R.id.widget_next, broadcast(context, ACTION_NEXT, 2))
                v.setOnClickPendingIntent(R.id.widget_prev, broadcast(context, ACTION_PREV, 3))
            } else {
                v.setOnClickPendingIntent(R.id.widget_play, open)
                v.setOnClickPendingIntent(R.id.widget_next, open)
                v.setOnClickPendingIntent(R.id.widget_prev, open)
            }
            manager.updateAppWidget(ids, v)
        }
    }
}
