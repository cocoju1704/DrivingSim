package com.drivingsim.torapp

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextPaint
import android.text.style.ForegroundColorSpan
import com.meta.wearable.dat.display.views.ContentScope
import com.meta.wearable.dat.display.views.Direction
import com.meta.wearable.dat.display.views.ImageSize
import com.meta.wearable.dat.display.views.TextColor
import com.meta.wearable.dat.display.views.TextStyle

// The display SDK has no text colors or positions (TextColor: PRIMARY / SECONDARY only), so each
// view is drawn here as one 600x600 image and sent whole.
private const val WIDTH = 600 // display width and height in pixels
private const val PADDING = 32f
private const val IMAGE_SCALE = 0.5f // images are drawn at half the display resolution
private val ORANGE = Color.rgb(255, 140, 0) // PRE-ALERT, as on the simulator screen
private val RED = Color.rgb(255, 0, 0) // TOR: the brightest red the display can show
private val MODE_AUTO = Color.rgb(0, 190, 70) // mode badge background: saturated, bright on the additive
private val MODE_MANUAL = Color.rgb(30, 110, 255) // display, dark enough for the white text on it
private const val MODE_ON_RIGHT = true // mode badge at the bottom right; false: bottom left
private val LABEL = Color.rgb(0, 255, 255) // intervention text: the label before the ':', bright cyan stands out on the additive display
private const val TEXT_HEIGHT = 480 // intervention text: from the top, above the mode text

/**
 * The overlay of takeover_experiment.py (TakeoverExperiment.render) on the glasses, without
 * backgrounds so the road stays visible. The display is 600x600, additive (black is see-through)
 * and in the right lens only; its top edge is at the center of the field of view.
 *   AUTO / MANUAL   small oval badge (white text on green / blue) at the bottom right
 *   PRE_ALERT       the message (the PC's, "곧 자율주행 구간이 끝납니다") in orange in the center
 *                   while there is no intervention text, the text at the top instead of it
 *   TOR             the message ("지금 직접 운전하세요") in red in the center, blinking (dim: off)
 */
fun ContentScope.torContent(view: GlassesView) {
  when (view.test) {
    DisplayTest.AREA -> {
      flexBox { image(bitmap = areaTest(), sizePreset = ImageSize.FILL) }
      return
    }
    DisplayTest.TEXT -> {
      textTest()
      return
    }
    null -> Unit
  }
  flexBox(direction = Direction.COLUMN, gap = 12) {
    if (view.mode == TorMode.OFF) {
      text("TORApp", style = TextStyle.BODY)
      text("Waiting for the simulator", style = TextStyle.META, color = TextColor.SECONDARY)
      return@flexBox
    }
    image(bitmap = frame(view), sizePreset = ImageSize.FILL)
  }
}

/** The image the glasses show for `view` (transparent where they are see-through), for the recording. */
fun glassesImage(view: GlassesView): Bitmap = frame(view)

private fun frame(view: GlassesView): Bitmap {
  val showText = view.mode == TorMode.PRE_ALERT && view.text.isNotEmpty()
  // full resolution: the Korean text is unreadable at IMAGE_SCALE
  val (bitmap, canvas) = blank(WIDTH, scale = 1f)
  if (view.mode == TorMode.TOR) {
    if (!view.dim) drawAlert(canvas, view.message, RED)
    return bitmap
  }
  if (showText) drawText(canvas, view.text)
  else if (view.mode == TorMode.PRE_ALERT) drawAlert(canvas, view.message, ORANGE)
  drawMode(canvas, view)
  return bitmap
}

/** The alert message, large and bold in `color`, wrapped and centered in the middle of the display. */
private fun drawAlert(canvas: Canvas, message: String, color: Int) {
  val width = (WIDTH - 2 * PADDING).toInt()
  val paint =
      TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        this.color = color
        textSize = 76f
        typeface = Typeface.DEFAULT_BOLD
      }
  val layout =
      StaticLayout.Builder.obtain(message, 0, message.length, paint, width)
          .setAlignment(Layout.Alignment.ALIGN_CENTER)
          .setLineSpacing(10f, 1f)
          .build()
  canvas.save()
  canvas.translate(PADDING, (WIDTH - layout.height) / 2f - 40f)
  layout.draw(canvas)
  canvas.restore()
}

/**
 * Small oval badge at the bottom right (MODE_ON_RIGHT, else left): AUTO on green while autonomous
 * (also during the alerts), MANUAL on blue, white text. Short on purpose; the simulator's longer
 * label (view.label) is not used here.
 */
private fun drawMode(canvas: Canvas, view: GlassesView) {
  val text = if (view.mode == TorMode.MANUAL) "MANUAL" else "AUTO"
  val paint = textPaint(45f, bold = true)
  val height = 78f
  val width = paint.measureText(text) + height // half the height of padding on each side
  val left = if (MODE_ON_RIGHT) WIDTH - PADDING - width else PADDING
  val top = WIDTH - PADDING - height
  canvas.drawRoundRect(
      RectF(left, top, left + width, top + height), height / 2, height / 2,
      fillPaint(if (view.mode == TorMode.MANUAL) MODE_MANUAL else MODE_AUTO))
  val metrics = paint.fontMetrics
  canvas.drawText(text, left + height / 2, top + height / 2 - (metrics.ascent + metrics.descent) / 2, paint)
}

/**
 * Intervention lines in bold white from the top, wrapped to the display width, a gap between
 * lines. The part of a line up to its first ':' (the label, e.g. "완료된 작업:") is in bright cyan,
 * on a line of its own, the rest below it. The font starts large and shrinks until all of it fits
 * in TEXT_HEIGHT.
 */
private fun drawText(canvas: Canvas, lines: List<String>) {
  val text = SpannableStringBuilder()
  for ((i, line) in lines.withIndex()) {
    if (i > 0) text.append('\n')
    val colon = line.indexOf(':')
    if (colon > 0) {
      val start = text.length
      text.append(line, 0, colon + 1)
      text.setSpan(ForegroundColorSpan(LABEL), start, text.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
      text.append('\n').append(line.substring(colon + 1).trim())
    } else {
      text.append(line)
    }
  }
  val width = (WIDTH - 2 * PADDING).toInt()
  var size = 64f
  var layout: StaticLayout
  while (true) {
    val paint =
        TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
          color = Color.WHITE
          textSize = size
          typeface = Typeface.DEFAULT_BOLD
        }
    layout =
        StaticLayout.Builder.obtain(text, 0, text.length, paint, width)
            .setAlignment(Layout.Alignment.ALIGN_NORMAL)
            .setLineSpacing(size * 0.25f, 1f)
            .build()
    if (layout.height <= TEXT_HEIGHT || size <= 28f) break
    size -= 2f
  }
  canvas.save()
  canvas.translate(PADDING, 0f)
  layout.draw(canvas)
  canvas.restore()
}

/** 600x600: white border, 100 px grid with labels, center cross. Shows what part is visible. */
private fun areaTest(): Bitmap {
  val (bitmap, canvas) = blank(WIDTH, scale = 1f) // full resolution: it measures the display
  val grid = Paint().apply { color = Color.rgb(90, 90, 90); strokeWidth = 2f }
  val bright = Paint().apply { color = Color.WHITE; strokeWidth = 4f; style = Paint.Style.STROKE }
  val labels = textPaint(22f, bold = false).apply { color = Color.rgb(200, 200, 200) }
  for (x in 100 until WIDTH step 100) {
    canvas.drawLine(x.toFloat(), 0f, x.toFloat(), WIDTH.toFloat(), grid)
    canvas.drawLine(0f, x.toFloat(), WIDTH.toFloat(), x.toFloat(), grid)
    canvas.drawText("$x", x + 4f, 24f, labels)
    canvas.drawText("$x", 6f, x - 6f, labels)
  }
  canvas.drawRect(2f, 2f, WIDTH - 2f, WIDTH - 2f, bright)
  val c = WIDTH / 2f
  canvas.drawLine(c - 40f, c, c + 40f, c, bright)
  canvas.drawLine(c, c - 40f, c, c + 40f, bright)
  val corner = fillPaint(Color.rgb(255, 140, 0))
  for ((x, y) in listOf(0f to 0f, WIDTH - 40f to 0f, 0f to WIDTH - 40f, WIDTH - 40f to WIDTH - 40f)) {
    canvas.drawRect(x, y, x + 40f, y + 40f, corner)
  }
  val title = textPaint(40f, bold = true).apply { textAlign = Paint.Align.CENTER }
  canvas.drawText("600 x 600", c, c + 90f, title)
  return bitmap
}

/** Native text in the three styles, numbered, so the visible lines and the scrolling show. */
private fun ContentScope.textTest() {
  flexBox(direction = Direction.COLUMN, gap = 4) {
    text("HEADING 1 TAKE OVER NOW!", style = TextStyle.HEADING)
    text("HEADING 2 Manual driving in 5 s", style = TextStyle.HEADING)
    for (i in 1..12) {
      text("BODY $i  The quick brown fox jumps over the lazy dog", style = TextStyle.BODY)
    }
    for (i in 1..6) {
      text("META $i  The quick brown fox jumps over the lazy dog", style = TextStyle.META)
    }
    text("END", style = TextStyle.HEADING)
  }
}

/**
 * Transparent bitmap (see-through on the glasses, like black) and a canvas drawing in display
 * pixels (600 wide). The SDK sends each image whole over Bluetooth, PNG when it has transparent
 * pixels: drawn at IMAGE_SCALE of the display size and stretched back by ImageSize.FILL, a view
 * is about a quarter of the data, so the countdown keeps up with the PC.
 */
private fun blank(height: Int, scale: Float = IMAGE_SCALE): Pair<Bitmap, Canvas> {
  val bitmap =
      Bitmap.createBitmap((WIDTH * scale).toInt(), (height * scale).toInt(), Bitmap.Config.ARGB_8888)
  bitmap.eraseColor(Color.TRANSPARENT)
  return bitmap to Canvas(bitmap).apply { scale(scale, scale) }
}

private fun fillPaint(color: Int) =
    Paint(Paint.ANTI_ALIAS_FLAG).apply {
      this.color = color
      style = Paint.Style.FILL
    }

private fun textPaint(size: Float, bold: Boolean) =
    Paint(Paint.ANTI_ALIAS_FLAG).apply {
      color = Color.WHITE
      textSize = size
      typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
    }
